"""
M4 — Referral attribution.

Partners get a unique quiz link (quiz_base_url?ref=CODE).
When a lead submits via that link, we record the attribution and
maintain a ledger of leads, bookings, closed deals, and fees owed.

Ledger stored at /opt/newdoor/data/referral_ledger.json.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LEDGER_PATH  = Path('/opt/newdoor/data/referral_ledger.json')
QUIZ_BASE_URL = os.getenv('QUIZ_BASE_URL', 'https://link.newdoorinvestments.net/feasibility-quiz')

# Default finder fee (% of consulting deal value). Override per partner.
DEFAULT_FEE_PERCENT = 1.0


# ── Ledger I/O ────────────────────────────────────────────────────────────────

def _load() -> dict:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text())
        except Exception:
            pass
    return {'partners': {}}


def _save(data: dict):
    LEDGER_PATH.write_text(json.dumps(data, indent=2))


# ── Partner management ────────────────────────────────────────────────────────

def register_partner(code: str, name: str, partner_type: str,
                     fee_percent: float = DEFAULT_FEE_PERCENT) -> dict:
    """
    Add or update a referral partner.
    partner_type: broker | builder | attorney | engineer | title | other
    """
    code = code.upper().strip()
    data = _load()
    existing = data['partners'].get(code, {})

    data['partners'][code] = {
        'name':            name,
        'type':            partner_type,
        'quiz_link':       generate_quiz_link(code),
        'fee_percent':     fee_percent,
        'leads_count':     existing.get('leads_count', 0),
        'booked_count':    existing.get('booked_count', 0),
        'deals_closed':    existing.get('deals_closed', 0),
        'deal_value_total': existing.get('deal_value_total', 0),
        'fee_owed':        existing.get('fee_owed', 0.0),
        'fee_paid':        existing.get('fee_paid', 0.0),
        'created_at':      existing.get('created_at', datetime.utcnow().isoformat()),
        'updated_at':      datetime.utcnow().isoformat(),
    }
    _save(data)
    logger.info('Partner registered: %s (%s)', code, name)
    return data['partners'][code]


def generate_quiz_link(code: str) -> str:
    return f'{QUIZ_BASE_URL}?ref={code.upper()}'


def get_partner(code: str) -> Optional[dict]:
    return _load()['partners'].get(code.upper())


def list_partners() -> list[dict]:
    data = _load()
    return [{'code': k, **v} for k, v in data['partners'].items()]


# ── Ledger updates ────────────────────────────────────────────────────────────

def record_lead(partner_code: str):
    """Called when a quiz submission is attributed to this partner."""
    code = partner_code.upper()
    data = _load()
    if code not in data['partners']:
        logger.warning('Unknown partner code %s — skipping ledger update', code)
        return
    data['partners'][code]['leads_count'] += 1
    data['partners'][code]['updated_at'] = datetime.utcnow().isoformat()
    _save(data)
    logger.info('Ledger: lead recorded for partner %s (total: %d)',
                code, data['partners'][code]['leads_count'])


def record_booking(partner_code: str):
    """Called when a lead attributed to this partner books a call."""
    code = partner_code.upper()
    data = _load()
    if code not in data['partners']:
        return
    data['partners'][code]['booked_count'] += 1
    data['partners'][code]['updated_at'] = datetime.utcnow().isoformat()
    _save(data)
    logger.info('Ledger: booking recorded for partner %s (total: %d)',
                code, data['partners'][code]['booked_count'])


def record_deal(partner_code: str, deal_value: float):
    """
    Called when a deal closes on a lead attributed to this partner.
    Computes fee_owed = deal_value * fee_percent / 100.
    """
    code = partner_code.upper()
    data = _load()
    if code not in data['partners']:
        return
    p = data['partners'][code]
    p['deals_closed']     += 1
    p['deal_value_total'] += deal_value
    p['fee_owed']         += round(deal_value * p['fee_percent'] / 100, 2)
    p['updated_at']        = datetime.utcnow().isoformat()
    _save(data)
    logger.info('Ledger: deal $%.0f recorded for partner %s — fee owed now $%.2f',
                deal_value, code, p['fee_owed'])


def mark_fee_paid(partner_code: str, amount: float):
    code = partner_code.upper()
    data = _load()
    if code not in data['partners']:
        return
    data['partners'][code]['fee_paid'] += amount
    data['partners'][code]['updated_at'] = datetime.utcnow().isoformat()
    _save(data)
    logger.info('Ledger: $%.2f fee marked paid for partner %s', amount, code)
