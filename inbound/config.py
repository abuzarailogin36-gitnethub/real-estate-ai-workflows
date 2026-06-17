import os, sys
sys.path.insert(0, '/opt/newdoor/scripts')
from config import (
    GHL_API_KEY, GHL_LOCATION, GHL_BASE, GHL_HEADERS,
    PIPELINE_ID, PIPELINE_STAGES, WORKFLOWS,
    SLACK_BOT_TOKEN,
)

CALENDAR_ID          = '3hKngMqdqTbx1Gz1Q3bF'
REGRID_API_KEY       = os.getenv('REGRID_API_KEY', '')
SLACK_ALERTS_CHANNEL = os.getenv('SLACK_ALERTS_CHANNEL', '#newdoor-leads')
WEBHOOK_SECRET       = os.getenv('INBOUND_WEBHOOK_SECRET', '')

HOT_MIN  = 70
WARM_MIN = 40

# Written by setup_fields.py on first deploy
FIELD_IDS_PATH = '/opt/newdoor/data/inbound_field_ids.json'

# Canonical field names (keys match GHL fieldKey suffix)
FIELD_NAMES = [
    'parcel_address', 'persona', 'need', 'timeline', 'site_stage',
    'acreage', 'lead_score', 'fit_score', 'intent_score', 'band',
    'referral_partner', 'quiz_source', 'sms_optin',
]
