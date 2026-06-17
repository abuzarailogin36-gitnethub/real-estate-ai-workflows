"""
M5 — Shared report engine for daily and weekly Slack summaries.
Pulls inbound contacts from GHL (tagged 'inbound') + referral ledger.
"""
import json
import logging
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import GHL_LOCATION, GHL_BASE, GHL_HEADERS, SLACK_BOT_TOKEN
from inbound.config import SLACK_ALERTS_CHANNEL
from inbound.referral import list_partners

logger = logging.getLogger(__name__)

BOOKING_URL = 'https://api.leadconnectorhq.com/widget/bookings/newclientmeetings'

# ── GHL data pull ─────────────────────────────────────────────────────────────

def fetch_inbound_contacts(since: datetime) -> list[dict]:
    """Return all inbound quiz contacts created after `since` (UTC-aware)."""
    r = requests.post(
        f'{GHL_BASE}/contacts/search',
        headers=GHL_HEADERS,
        json={
            'locationId': GHL_LOCATION,
            'filters': [{'field': 'tags', 'operator': 'contains', 'value': 'inbound'}],
            'pageLimit': 100,
        },
        timeout=30,
    )
    if not r.ok:
        logger.warning('GHL contact search failed: %s', r.status_code)
        return []

    contacts = r.json().get('contacts', [])
    result = []
    for c in contacts:
        added_str = c.get('dateAdded', '')
        try:
            added = datetime.fromisoformat(added_str.replace('Z', '+00:00'))
            if added >= since:
                result.append(c)
        except Exception:
            pass
    return result


def parse_tags(tags: list) -> dict:
    """Extract structured fields from contact tags."""
    out = {'band': 'unknown', 'source': 'unknown', 'partner': None, 'persona': None}
    for t in tags:
        if t.startswith('band:'):
            out['band'] = t.split(':', 1)[1]
        elif t.startswith('source:'):
            out['source'] = t.split(':', 1)[1]
        elif t.startswith('partner:'):
            out['partner'] = t.split(':', 1)[1].upper()
        elif t.startswith('persona:'):
            out['persona'] = t.split(':', 1)[1]
    return out


# ── Slack posting ─────────────────────────────────────────────────────────────

def post_to_slack(blocks: list, channel: str = None):
    channel = channel or SLACK_ALERTS_CHANNEL
    r = requests.post(
        'https://slack.com/api/chat.postMessage',
        headers={'Authorization': f'Bearer {SLACK_BOT_TOKEN}', 'Content-Type': 'application/json'},
        json={'channel': channel, 'blocks': blocks},
        timeout=15,
    )
    data = r.json() if r.ok else {}
    if data.get('ok'):
        logger.info('Summary posted to %s', channel)
    else:
        logger.warning('Slack post failed: %s', data.get('error', r.text[:100]))


# ── Daily summary ─────────────────────────────────────────────────────────────

def run_daily_summary():
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    contacts = fetch_inbound_contacts(since)

    total = len(contacts)
    bands = {'hot': [], 'warm': [], 'cold': []}
    sources = {}

    for c in contacts:
        info  = parse_tags(c.get('tags', []))
        band  = info['band']
        bands.setdefault(band, []).append(c)
        src = info['source']
        sources[src] = sources.get(src, 0) + 1

    hot_lines = []
    for c in bands.get('hot', []):
        info = parse_tags(c.get('tags', []))
        name = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() or 'Unknown'
        hot_lines.append(f'• {name} — {info["persona"] or "—"} via {info["source"]}')

    src_text = '  '.join(f'{k}: {v}' for k, v in sorted(sources.items())) or 'none'

    blocks = [
        {'type': 'header', 'text': {'type': 'plain_text',
            'text': f'📋 Daily Lead Summary — {datetime.now().strftime("%a %b %-d")}'}},
        {'type': 'section', 'fields': [
            {'type': 'mrkdwn', 'text': f'*New leads (24h)*\n{total}'},
            {'type': 'mrkdwn', 'text': f'*Hot 🔥 / Warm / Cold*\n{len(bands.get("hot",[]))} / {len(bands.get("warm",[]))} / {len(bands.get("cold",[]))}'},
        ]},
        {'type': 'section', 'text': {'type': 'mrkdwn', 'text': f'*Sources:* {src_text}'}},
    ]

    if hot_lines:
        blocks.append({'type': 'section', 'text': {
            'type': 'mrkdwn',
            'text': '*Hot leads:*\n' + '\n'.join(hot_lines),
        }})

    if total == 0:
        blocks.append({'type': 'section', 'text': {
            'type': 'mrkdwn', 'text': '_No new inbound leads in the last 24 hours._',
        }})

    blocks.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': f'<{BOOKING_URL}|📅 Booking link>'}})

    post_to_slack(blocks)
    logger.info('Daily summary: %d leads (hot=%d warm=%d cold=%d)',
                total, len(bands.get('hot',[])), len(bands.get('warm',[])), len(bands.get('cold',[])))


# ── Weekly KPI report ─────────────────────────────────────────────────────────

def run_weekly_report():
    since = datetime.now(timezone.utc) - timedelta(days=7)
    contacts = fetch_inbound_contacts(since)

    total = len(contacts)
    bands   = {'hot': 0, 'warm': 0, 'cold': 0}
    sources = {}
    booked  = 0

    for c in contacts:
        info = parse_tags(c.get('tags', []))
        band = info['band']
        if band in bands:
            bands[band] += 1
        src = info['source']
        sources[src] = sources.get(src, 0) + 1
        if 'appointment_set' in c.get('tags', []) or band == 'hot':
            # approximate booked count from appointment stage tags
            pass

    qualified = bands['hot'] + bands['warm']
    qual_pct  = round(qualified / total * 100) if total else 0

    # Booked: contacts tagged band:hot that have been moved to appointment stage
    # Best proxy without a separate tracker: check opportunities (deferred — use hot count as floor)
    booked = bands['hot']   # floor: every hot lead got a booking offer

    booked_rate = round(booked / total * 100) if total else 0

    src_lines = '\n'.join(
        f'  • {k.capitalize()}: {v} ({round(v/total*100) if total else 0}%)'
        for k, v in sorted(sources.items(), key=lambda x: -x[1])
    ) or '  • none'

    # Referral ledger
    partners = list_partners()
    ref_total_leads = sum(p['leads_count'] for p in partners)
    ref_total_fees  = sum(p['fee_owed'] for p in partners)
    partner_lines = '\n'.join(
        f'  • {p["name"]} ({p["code"]}): {p["leads_count"]} leads, '
        f'{p["booked_count"]} booked, ${p["fee_owed"]:.0f} fee owed'
        for p in sorted(partners, key=lambda x: -x['leads_count'])
    ) or '  • No partners registered yet'

    blocks = [
        {'type': 'header', 'text': {'type': 'plain_text',
            'text': f'📊 Weekly KPI Report — {datetime.now().strftime("Week of %b %-d")}'}},
        {'type': 'section', 'fields': [
            {'type': 'mrkdwn', 'text': f'*Total leads*\n{total}'},
            {'type': 'mrkdwn', 'text': f'*Auto-qualified*\n{qualified} ({qual_pct}%)'},
            {'type': 'mrkdwn', 'text': f'*Hot 🔥*\n{bands["hot"]}'},
            {'type': 'mrkdwn', 'text': f'*Warm*\n{bands["warm"]}'},
            {'type': 'mrkdwn', 'text': f'*Cold*\n{bands["cold"]}'},
            {'type': 'mrkdwn', 'text': f'*Booking offers sent*\n{booked} ({booked_rate}%)'},
        ]},
        {'type': 'divider'},
        {'type': 'section', 'text': {'type': 'mrkdwn',
            'text': f'*Source breakdown:*\n{src_lines}'}},
        {'type': 'divider'},
        {'type': 'section', 'text': {'type': 'mrkdwn',
            'text': f'*Referral partners* — {ref_total_leads} leads, ${ref_total_fees:.0f} total fees owed:\n{partner_lines}'}},
        {'type': 'divider'},
        {'type': 'section', 'text': {'type': 'mrkdwn',
            'text': f'<{BOOKING_URL}|📅 Booking link>  |  North star: signed deals & retainers'}},
    ]

    post_to_slack(blocks)
    logger.info('Weekly report: %d leads, %d%% qualified', total, qual_pct)
