"""
M3 — Booking module.

Flow:
  1. get_free_slots()  → pick first 2 available slots from Mir's calendar
  2. send_slot_offer() → SMS the lead with "reply 1 or 2"
  3. /webhooks/reply   → on inbound SMS, confirm_booking() or handle_opt_out()
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

from config import GHL_API_KEY, GHL_LOCATION, GHL_BASE, GHL_HEADERS
from inbound.config import CALENDAR_ID

logger = logging.getLogger(__name__)

PENDING_PATH = Path('/opt/newdoor/data/pending_bookings.json')
TIMEZONE     = 'America/Chicago'
SLOT_WINDOW_DAYS = 7   # look this many days ahead


# ── Slot fetching ─────────────────────────────────────────────────────────────

def get_free_slots(count: int = 2) -> list[str]:
    """Return up to `count` upcoming ISO 8601 slot strings from Mir's calendar."""
    now_ms = int(time.time() * 1000)
    end_ms = now_ms + SLOT_WINDOW_DAYS * 24 * 60 * 60 * 1000

    r = requests.get(
        f'{GHL_BASE}/calendars/{CALENDAR_ID}/free-slots',
        headers=GHL_HEADERS,
        params={'startDate': now_ms, 'endDate': end_ms, 'timezone': TIMEZONE},
        timeout=30,
    )
    if not r.ok:
        logger.warning('Free slots fetch failed: %s %s', r.status_code, r.text[:200])
        return []

    data = r.json()
    # Response: {"2026-06-19": {"slots": [...]}, "2026-06-20": {...}, "traceId": "..."}
    slots = []
    for day in sorted(k for k in data if k[:4].isdigit()):   # skip non-date keys
        for s in data[day].get('slots', []):
            slots.append(s)
            if len(slots) >= count:
                return slots
    return slots


def format_slot(iso: str) -> str:
    """'2026-06-19T09:00:00-05:00' → 'Fri Jun 19 at 9:00 AM CT'"""
    dt = datetime.fromisoformat(iso)
    return dt.strftime('%a %b %-d at %-I:%M %p CT')


# ── SMS sending ───────────────────────────────────────────────────────────────

def send_slot_offer(contact_id: str, name: str, parcel: str, slots: list[str]) -> bool:
    """SMS the lead with two slot options. Returns True on success."""
    if not slots:
        logger.warning('No slots available to offer contact %s', contact_id)
        return False

    first_name = name.split()[0] if name else 'there'
    city = parcel.split(',')[1].strip() if ',' in parcel else parcel

    lines = [
        f'Hi {first_name} — Mir here from New Door Investments.',
        f'',
        f"I'd love a quick free call about your land in {city}.",
        f'',
        f'Here are two times I have open:',
    ]
    for i, slot in enumerate(slots, 1):
        lines.append(f'  {i}. {format_slot(slot)}')
    lines += [
        f'',
        f'Reply *1* or *2* to confirm.',
        f'Reply STOP to opt out.',
    ]

    message = '\n'.join(lines)
    success = _send_sms(contact_id, message)

    if success:
        _save_pending(contact_id, slots)
        logger.info('Slot offer sent to %s (%s)', contact_id, name)

    return success


def _send_sms(contact_id: str, message: str) -> bool:
    r = requests.post(
        f'{GHL_BASE}/conversations/messages',
        headers=GHL_HEADERS,
        json={'contactId': contact_id, 'type': 'SMS', 'message': message},
        timeout=30,
    )
    if r.ok:
        return True
    logger.warning('SMS send failed: %s %s', r.status_code, r.text[:200])
    return False


# ── Pending state ─────────────────────────────────────────────────────────────

def _save_pending(contact_id: str, slots: list[str]):
    data = _load_pending()
    data[contact_id] = {'slots': slots, 'offered_at': datetime.utcnow().isoformat()}
    PENDING_PATH.write_text(json.dumps(data, indent=2))


def _load_pending() -> dict:
    if PENDING_PATH.exists():
        try:
            return json.loads(PENDING_PATH.read_text())
        except Exception:
            pass
    return {}


def get_pending_slots(contact_id: str) -> list[str]:
    return _load_pending().get(contact_id, {}).get('slots', [])


def clear_pending(contact_id: str):
    data = _load_pending()
    data.pop(contact_id, None)
    PENDING_PATH.write_text(json.dumps(data, indent=2))


# ── Booking confirmation ──────────────────────────────────────────────────────

def confirm_booking(contact_id: str, name: str, slot_iso: str) -> Optional[str]:
    """Create appointment in GHL. Returns appointment ID or None."""
    dt_start = datetime.fromisoformat(slot_iso)
    dt_end   = dt_start + timedelta(minutes=30)

    payload = {
        'calendarId':        CALENDAR_ID,
        'locationId':        GHL_LOCATION,
        'contactId':         contact_id,
        'startTime':         slot_iso,
        'endTime':           dt_end.isoformat(),
        'title':             f'New Door Feasibility Call — {name}',
        'meetingLocationType': 'custom',
        'address':           'Phone Call',
    }
    r = requests.post(
        f'{GHL_BASE}/calendars/events/appointments',
        headers=GHL_HEADERS,
        json=payload,
        timeout=30,
    )
    if r.ok:
        appt_id = r.json().get('id') or r.json().get('appointment', {}).get('id')
        logger.info('Appointment created %s for %s at %s', appt_id, contact_id, slot_iso)
        return appt_id
    logger.warning('Appointment creation failed: %s %s', r.status_code, r.text[:200])
    return None


def send_confirmation_sms(contact_id: str, name: str, slot_iso: str):
    first_name = name.split()[0] if name else 'there'
    slot_str   = format_slot(slot_iso)
    message = (
        f"You're all set, {first_name}! 🎉\n\n"
        f"*New Door Feasibility Call*\n"
        f"{slot_str}\n\n"
        f"Mir will call you at this number. See you then!"
    )
    _send_sms(contact_id, message)


# ── Opt-out ───────────────────────────────────────────────────────────────────

def handle_opt_out(contact_id: str):
    """Tag DNC and remove from all active workflows immediately."""
    from inbound.router import _enroll_workflow
    from config import WORKFLOWS

    clear_pending(contact_id)

    # Add DNC tag
    requests.post(
        f'{GHL_BASE}/contacts/{contact_id}/tags',
        headers=GHL_HEADERS,
        json={'tags': ['DNC', 'opted-out']},
        timeout=15,
    )

    # Enroll in DNC workflow (stops all sequences)
    dnc_wf = WORKFLOWS.get('dnc')
    if dnc_wf:
        _enroll_workflow(contact_id, dnc_wf)

    logger.info('Opt-out processed for contact %s — tagged DNC', contact_id)
