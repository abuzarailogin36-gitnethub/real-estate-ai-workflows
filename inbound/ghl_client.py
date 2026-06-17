import json
import logging
import requests
from typing import Optional

from config import (
    GHL_API_KEY, GHL_LOCATION, GHL_BASE, GHL_HEADERS,
    PIPELINE_ID, PIPELINE_STAGES,
)
from inbound.config import FIELD_IDS_PATH

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TIMEOUT = 30


def _get(path: str, params: dict = None) -> Optional[dict]:
    r = requests.get(f'{GHL_BASE}{path}', headers=GHL_HEADERS, params=params, timeout=_TIMEOUT)
    if r.ok:
        return r.json()
    logger.warning('GHL GET %s → %s %s', path, r.status_code, r.text[:200])
    return None


def _post(path: str, body: dict) -> Optional[dict]:
    r = requests.post(f'{GHL_BASE}{path}', headers=GHL_HEADERS, json=body, timeout=_TIMEOUT)
    if r.ok:
        return r.json()
    # GHL returns 400 + meta.contactId when allowDuplicateContact=false blocks creation
    if r.status_code == 400:
        try:
            meta = r.json().get('meta', {})
            dup_id = meta.get('contactId')
            if dup_id:
                logger.info('GHL duplicate contact detected, using existing id=%s', dup_id)
                return {'_duplicate': True, 'contact': {'id': dup_id}}
        except Exception:
            pass
    logger.warning('GHL POST %s → %s %s', path, r.status_code, r.text[:200])
    return None


def _put(path: str, body: dict) -> Optional[dict]:
    r = requests.put(f'{GHL_BASE}{path}', headers=GHL_HEADERS, json=body, timeout=_TIMEOUT)
    if r.ok:
        return r.json()
    logger.warning('GHL PUT %s → %s %s', path, r.status_code, r.text[:200])
    return None


def _load_field_ids() -> dict:
    try:
        with open(FIELD_IDS_PATH) as f:
            return json.load(f)
    except Exception:
        logger.error('Field ID map not found at %s — run setup_fields.py first', FIELD_IDS_PATH)
        return {}

# ── Contact ───────────────────────────────────────────────────────────────────

def find_contact_by_phone(phone: str) -> Optional[str]:
    data = _get('/contacts/', {'locationId': GHL_LOCATION, 'query': phone, 'limit': 5})
    if not data:
        return None
    for c in data.get('contacts', []):
        for p in c.get('phones', []):
            if p.get('number', '').replace(' ', '') == phone:
                return c['id']
    return None


def upsert_contact(submission: dict, score_result, field_ids: dict) -> Optional[str]:
    """
    Create or update a GHL contact from a quiz submission.
    submission keys: name, email, phone, parcel_address, persona, need,
                     timeline, site_stage, acreage, source, referral_partner, sms_optin
    """
    phone = submission.get('phone', '')
    existing_id = find_contact_by_phone(phone) if phone else None

    name_parts = submission.get('name', '').split(' ', 1)
    first = name_parts[0]
    last  = name_parts[1] if len(name_parts) > 1 else ''

    custom_fields = _build_custom_fields(submission, score_result, field_ids)

    tags = _build_tags(submission, score_result)

    payload = {
        'locationId': GHL_LOCATION,
        'firstName':  first,
        'lastName':   last,
        'email':      submission.get('email') or None,
        'phone':      phone or None,
        'source':     'Feasibility Quiz',
        'tags':       tags,
        'customFields': custom_fields,
    }
    payload = {k: v for k, v in payload.items() if v is not None and v != ''}

    # GHL PUT rejects locationId — strip it for updates
    update_payload = {k: v for k, v in payload.items() if k != 'locationId'}

    if existing_id:
        _put(f'/contacts/{existing_id}', update_payload)
        logger.info('Updated contact %s (%s)', existing_id, submission.get('name'))
        return existing_id

    result = _post('/contacts/', payload)
    if not result:
        return None

    contact_id = (result.get('contact') or {}).get('id') or result.get('id')

    # If GHL returned a duplicate, update that contact with our fields
    if result.get('_duplicate') and contact_id:
        _put(f'/contacts/{contact_id}', update_payload)
        logger.info('Updated duplicate contact %s (%s)', contact_id, submission.get('name'))

    return contact_id


def _build_custom_fields(submission: dict, score_result, field_ids: dict) -> list:
    mapping = {
        'parcel_address': submission.get('parcel_address', ''),
        'persona':        submission.get('persona', ''),
        'need':           submission.get('need', ''),
        'timeline':       submission.get('timeline', ''),
        'site_stage':     submission.get('site_stage', ''),
        'acreage':        str(submission.get('acreage', '')),
        'lead_score':     str(score_result.total),
        'fit_score':      str(score_result.fit),
        'intent_score':   str(score_result.intent),
        'band':           score_result.band,
        'referral_partner': submission.get('referral_partner', ''),
        'quiz_source':    submission.get('source', 'quiz'),
        'sms_optin':      'true' if submission.get('sms_optin') else 'false',
    }
    return [
        {'id': field_ids[k], 'field_value': v}
        for k, v in mapping.items()
        if k in field_ids and v
    ]


def _build_tags(submission: dict, score_result) -> list:
    tags = ['inbound', 'feasibility-quiz']

    source = submission.get('source', 'website')
    tags.append(f'source:{source}')

    persona = submission.get('persona', '')
    if persona:
        tags.append(f'persona:{persona}')

    need = submission.get('need', '')
    if need:
        tags.append(f'goal:{need}')

    tags.append(f'band:{score_result.band}')

    ref = submission.get('referral_partner', '')
    if ref:
        tags.append(f'partner:{ref}')

    return tags

# ── Opportunity ───────────────────────────────────────────────────────────────

def find_opportunity(contact_id: str) -> Optional[str]:
    data = _get('/opportunities/search', {
        'location_id': GHL_LOCATION,
        'contact_id':  contact_id,
        'pipeline_id': PIPELINE_ID,
    })
    opps = (data or {}).get('opportunities', [])
    return opps[0]['id'] if opps else None


def upsert_opportunity(contact_id: str, submission: dict, stage_id: str) -> Optional[str]:
    city    = submission.get('city', submission.get('parcel_address', 'TX').split(',')[-2].strip() if ',' in submission.get('parcel_address', '') else 'TX')
    acreage = submission.get('acreage', '?')
    need    = submission.get('need', 'consult')
    name    = f'{city} - {acreage}ac - {need}'

    existing_id = find_opportunity(contact_id)

    payload = {
        'pipelineId':  PIPELINE_ID,
        'locationId':  GHL_LOCATION,
        'name':        name,
        'pipelineStageId': stage_id,
        'contactId':   contact_id,
        'status':      'open',
    }

    if existing_id:
        result = _put(f'/opportunities/{existing_id}', payload)
        logger.info('Updated opportunity %s → stage %s', existing_id, stage_id)
        return existing_id
    else:
        result = _post('/opportunities/', payload)
        opp_id = (result or {}).get('opportunity', {}).get('id') or (result or {}).get('id')
        logger.info('Created opportunity %s (%s)', opp_id, name)
        return opp_id
