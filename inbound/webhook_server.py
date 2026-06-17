"""
POST /webhooks/quiz  — receives GHL survey submissions, scores, routes.

GHL sends a form/survey webhook with this structure:
  {
    "type": "FormSubmitted",
    "locationId": "...",
    "contactId": "...",          # may be pre-existing or empty
    "formData": {
      "full_name": "...",
      "email": "...",
      "phone": "...",
      "parcel_address": "...",
      "persona": "...",
      "need": "...",
      "timeline": "...",
      "site_stage": "...",
      "acreage": "...",
      "sms_optin": "true"
    },
    "source": "...",             # UTM source / ref code passed as hidden field
    "referral_partner": "..."    # populated by referral attribution (M4)
  }

For direct testing, POST the same shape to /webhooks/quiz.
"""
import json
import logging
import os
import sys

sys.path.insert(0, '/opt/newdoor/scripts')

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from inbound.scoring import score
from inbound.regrid_client import lookup_parcel
from inbound.ghl_client import upsert_contact, upsert_opportunity, _load_field_ids
from inbound.router import route, BAND_STAGE
from inbound.slack_client import post_hot_lead_alert
from inbound.booking_client import (
    get_free_slots, send_slot_offer, confirm_booking,
    send_confirmation_sms, handle_opt_out, get_pending_slots, clear_pending,
)
from inbound.referral import record_lead, record_booking, register_partner, list_partners, get_partner
from inbound.config import WEBHOOK_SECRET

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s — %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/newdoor/logs/inbound_webhook.log'),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI(title='New Door Inbound Engine', version='1.0.0')


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/webhooks/quiz')
async def quiz_webhook(request: Request):
    # Optional secret validation
    if WEBHOOK_SECRET:
        secret = request.headers.get('x-webhook-secret', '')
        if secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail='Invalid webhook secret')

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')

    logger.info('Quiz webhook received: %s', json.dumps(payload)[:500])

    # ── 1. Parse submission ────────────────────────────────────────────────
    form = payload.get('formData') or payload.get('form_data') or payload
    submission = {
        'name':             form.get('full_name') or form.get('name', ''),
        'email':            form.get('email', ''),
        'phone':            _normalise_phone(form.get('phone', '')),
        'parcel_address':   form.get('parcel_address', ''),
        'persona':          form.get('persona', ''),
        'need':             form.get('need', ''),
        'timeline':         form.get('timeline', ''),
        'site_stage':       form.get('site_stage', ''),
        'acreage':          form.get('acreage', ''),
        'sms_optin':        _truthy(form.get('sms_optin', False)),
        'source':           payload.get('source') or form.get('source', 'quiz'),
        'referral_partner': payload.get('referral_partner') or form.get('referral_partner', ''),
    }

    if not submission['phone'] and not submission['email']:
        raise HTTPException(status_code=422, detail='phone or email required')

    # ── 2. Enrich (Regrid — no-op until key set) ──────────────────────────
    parcel_data = {}
    if submission['parcel_address']:
        parcel_data = lookup_parcel(submission['parcel_address'])
        if parcel_data.get('ll_gisacre') and not submission['acreage']:
            submission['acreage'] = str(parcel_data['ll_gisacre'])

    # ── 3. Score ──────────────────────────────────────────────────────────
    result = score(submission)
    logger.info('Score: fit=%s intent=%s total=%s band=%s — %s',
                result.fit, result.intent, result.total, result.band,
                submission.get('name'))

    # ── 4. GHL upsert contact + fields + tags ─────────────────────────────
    field_ids = _load_field_ids()
    try:
        contact_id = upsert_contact(submission, result, field_ids)
    except Exception as exc:
        logger.error('GHL upsert error: %s', exc)
        raise HTTPException(status_code=502, detail='GHL API unavailable — try again')
    if not contact_id:
        raise HTTPException(status_code=502, detail='Failed to upsert GHL contact')

    # ── 5. Route → stage + workflow ───────────────────────────────────────
    stage_id = route(contact_id, result.band)

    # ── 6. Create/update opportunity ─────────────────────────────────────
    opp_id = upsert_opportunity(contact_id, submission, stage_id)

    # ── 7. Slack alert (hot leads only) ──────────────────────────────────
    post_hot_lead_alert(submission, result, contact_id, opp_id)

    # ── 8. Referral attribution ───────────────────────────────────────────
    ref = submission.get('referral_partner', '')
    if ref:
        record_lead(ref)

    # ── 9. Offer 2 booking slots via SMS (hot + SMS opt-in only) ─────────
    offered_slots = []
    if result.band == 'hot' and submission.get('sms_optin'):
        slots = get_free_slots(count=2)
        if slots:
            send_slot_offer(contact_id, submission['name'], submission.get('parcel_address', ''), slots)
            offered_slots = slots

    return JSONResponse({
        'contact_id':  contact_id,
        'opportunity_id': opp_id,
        'score': {
            'fit': result.fit,
            'intent': result.intent,
            'total': result.total,
            'band': result.band,
        },
    })


@app.post('/webhooks/reply')
async def reply_webhook(request: Request):
    """
    Receives inbound SMS replies from GHL (configured in a GHL workflow).
    Payload: { "contactId": "...", "message": "...", "contactName": "..." }
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')

    contact_id = payload.get('contactId') or payload.get('contact_id', '')
    raw_msg    = (payload.get('message') or payload.get('body') or '').strip()
    name       = payload.get('contactName') or payload.get('name', 'Lead')

    if not contact_id or not raw_msg:
        raise HTTPException(status_code=422, detail='contactId and message required')

    logger.info('Inbound reply from %s (%s): %s', contact_id, name, raw_msg[:100])

    # Opt-out — honour immediately, no further processing
    if raw_msg.upper() in ('STOP', 'UNSUBSCRIBE', 'CANCEL', 'QUIT', 'END'):
        handle_opt_out(contact_id)
        return JSONResponse({'action': 'opted_out', 'contact_id': contact_id})

    # Booking choice — "1" or "2"
    slots = get_pending_slots(contact_id)
    if slots and raw_msg in ('1', '2'):
        chosen = slots[int(raw_msg) - 1]
        appt_id = confirm_booking(contact_id, name, chosen)
        if appt_id:
            send_confirmation_sms(contact_id, name, chosen)
            clear_pending(contact_id)
            # Move opportunity to Appointment Set
            from inbound.ghl_client import find_opportunity, _put
            from config import PIPELINE_STAGES
            opp_id = find_opportunity(contact_id)
            if opp_id:
                _put(f'/opportunities/{opp_id}', {
                    'pipelineStageId': PIPELINE_STAGES['appointment_set'],
                })
            # Referral attribution — increment booking count
            ref_code = payload.get('referral_partner', '')
            if ref_code:
                record_booking(ref_code)
            logger.info('Booked: contact %s → appointment %s at %s', contact_id, appt_id, chosen)
            return JSONResponse({'action': 'booked', 'appointment_id': appt_id, 'slot': chosen})
        else:
            return JSONResponse({'action': 'booking_failed'}, status_code=502)

    # Unrecognised reply — log and ignore (conversation engine handles it)
    logger.info('Unrecognised reply from %s — passing to conversation engine', contact_id)
    return JSONResponse({'action': 'unrecognised'})


@app.get('/referrals/partners')
def get_partners():
    """List all referral partners and their ledger totals."""
    return JSONResponse({'partners': list_partners()})


@app.post('/referrals/partners')
async def add_partner(request: Request):
    """
    Register a new referral partner.
    Body: { "code": "BROKER01", "name": "Bob Smith", "type": "broker", "fee_percent": 1.0 }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')

    code = body.get('code', '').strip().upper()
    name = body.get('name', '').strip()
    if not code or not name:
        raise HTTPException(status_code=422, detail='code and name required')

    partner = register_partner(
        code=code,
        name=name,
        partner_type=body.get('type', 'other'),
        fee_percent=float(body.get('fee_percent', 1.0)),
    )
    return JSONResponse({'partner': partner})


def _normalise_phone(raw: str) -> str:
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        return f'+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'+{digits}'
    return raw


def _truthy(val) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).lower() in ('true', '1', 'yes')
