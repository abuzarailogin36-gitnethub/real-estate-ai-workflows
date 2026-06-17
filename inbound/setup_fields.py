"""
Run once on deploy to create the 13 inbound custom fields in GHL
and save their IDs to /opt/newdoor/data/inbound_field_ids.json.

Safe to re-run — skips fields that already exist.
"""
import json
import sys
import requests

sys.path.insert(0, '/opt/newdoor/scripts')
from config import GHL_API_KEY, GHL_LOCATION, GHL_BASE, GHL_HEADERS
from inbound.config import FIELD_IDS_PATH

FIELDS_TO_CREATE = [
    {'name': 'Parcel Address',    'key': 'parcel_address',   'dataType': 'TEXT'},
    {'name': 'Persona',           'key': 'persona',          'dataType': 'TEXT'},
    {'name': 'Need',              'key': 'need',             'dataType': 'TEXT'},
    {'name': 'Timeline',          'key': 'timeline',         'dataType': 'TEXT'},
    {'name': 'Site Stage',        'key': 'site_stage',       'dataType': 'TEXT'},
    {'name': 'Acreage',           'key': 'acreage',          'dataType': 'NUMERICAL'},
    {'name': 'Lead Score',        'key': 'lead_score',       'dataType': 'NUMERICAL'},
    {'name': 'Fit Score',         'key': 'fit_score',        'dataType': 'NUMERICAL'},
    {'name': 'Intent Score',      'key': 'intent_score',     'dataType': 'NUMERICAL'},
    {'name': 'Band',              'key': 'band',             'dataType': 'TEXT'},
    {'name': 'Referral Partner',  'key': 'referral_partner', 'dataType': 'TEXT'},
    {'name': 'Quiz Source',       'key': 'quiz_source',      'dataType': 'TEXT'},
    {'name': 'SMS Opt-in',        'key': 'sms_optin',        'dataType': 'TEXT'},
]


def get_existing_fields() -> dict:
    """Returns {fieldKey_suffix: field_id} for all existing custom fields."""
    r = requests.get(
        f'{GHL_BASE}/locations/{GHL_LOCATION}/customFields',
        headers=GHL_HEADERS, timeout=15,
    )
    r.raise_for_status()
    existing = {}
    for f in r.json().get('customFields', []):
        key = f['fieldKey'].split('.')[-1]   # strip "contact." prefix
        existing[key] = f['id']
    return existing


def create_field(name: str, data_type: str) -> str:
    r = requests.post(
        f'{GHL_BASE}/locations/{GHL_LOCATION}/customFields',
        headers=GHL_HEADERS,
        json={'name': name, 'dataType': data_type, 'position': 0},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()['customField']['id']


def main():
    print('Fetching existing custom fields...')
    existing = get_existing_fields()
    field_ids = {}

    for spec in FIELDS_TO_CREATE:
        key = spec['key']
        if key in existing:
            field_ids[key] = existing[key]
            print(f'  ✓ {key} already exists ({existing[key]})')
        else:
            fid = create_field(spec['name'], spec['dataType'])
            field_ids[key] = fid
            print(f'  + created {key} ({fid})')

    with open(FIELD_IDS_PATH, 'w') as f:
        json.dump(field_ids, f, indent=2)
    print(f'\nSaved to {FIELD_IDS_PATH}')
    print(json.dumps(field_ids, indent=2))


if __name__ == '__main__':
    main()
