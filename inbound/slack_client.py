import logging
import requests

from config import SLACK_BOT_TOKEN
from inbound.config import SLACK_ALERTS_CHANNEL
from inbound.scoring import ScoreResult

logger = logging.getLogger(__name__)

BOOKING_URL = 'https://api.leadconnectorhq.com/widget/bookings/newclientmeetings'

_HEADERS = {
    'Authorization': f'Bearer {SLACK_BOT_TOKEN}',
    'Content-Type': 'application/json',
}


def post_hot_lead_alert(submission: dict, result: ScoreResult, contact_id: str, opp_id: str):
    """Post a hot-lead alert to the configured Slack alerts channel."""
    if result.band != 'hot':
        return

    message = _build_message(submission, result, contact_id)
    _send(SLACK_ALERTS_CHANNEL, message)


def _build_message(submission: dict, result: ScoreResult, contact_id: str) -> dict:
    name     = submission.get('name', 'Unknown')
    persona  = submission.get('persona', '—')
    parcel   = submission.get('parcel_address', '—')
    acreage  = submission.get('acreage', '—')
    need     = submission.get('need', '—')
    timeline = submission.get('timeline', '—')
    stage    = submission.get('site_stage', '—')
    source   = submission.get('source', '—')
    ref      = submission.get('referral_partner', '')

    source_line = f'source:{source}' + (f' via {ref}' if ref else '')

    return {
        'blocks': [
            {
                'type': 'header',
                'text': {'type': 'plain_text', 'text': f'🔥 HOT LEAD — {name}'},
            },
            {
                'type': 'section',
                'fields': [
                    {'type': 'mrkdwn', 'text': f'*Score*\n{result.total}/100 (Fit {result.fit} · Intent {result.intent})'},
                    {'type': 'mrkdwn', 'text': f'*Persona*\n{persona}'},
                    {'type': 'mrkdwn', 'text': f'*Parcel*\n{parcel}'},
                    {'type': 'mrkdwn', 'text': f'*Acreage*\n{acreage} ac'},
                    {'type': 'mrkdwn', 'text': f'*Need*\n{need}'},
                    {'type': 'mrkdwn', 'text': f'*Timeline*\n{timeline}'},
                    {'type': 'mrkdwn', 'text': f'*Site stage*\n{stage}'},
                    {'type': 'mrkdwn', 'text': f'*Source*\n{source_line}'},
                ],
            },
            {'type': 'divider'},
            {
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': f'<{BOOKING_URL}|📅 Book the free feasibility call>',
                },
            },
        ]
    }


def _send(channel: str, message: dict):
    payload = {'channel': channel, **message}
    r = requests.post(
        'https://slack.com/api/chat.postMessage',
        headers=_HEADERS,
        json=payload,
        timeout=15,
    )
    data = r.json() if r.ok else {}
    if data.get('ok'):
        logger.info('Slack alert sent to %s', channel)
    else:
        logger.warning('Slack alert failed: %s', data.get('error', r.text[:200]))
