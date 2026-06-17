import logging
import requests

from config import GHL_HEADERS, GHL_BASE, WORKFLOWS, PIPELINE_STAGES
from inbound.scoring import Band

logger = logging.getLogger(__name__)

# Band → pipeline stage
BAND_STAGE = {
    'hot':  PIPELINE_STAGES['appointment_set'],
    'warm': PIPELINE_STAGES['warm_considering'],
    'cold': PIPELINE_STAGES['contacted_not_ready'],
}

# Band → nurture workflow
BAND_WORKFLOW = {
    'hot':  WORKFLOWS['hot_lead'],
    'warm': WORKFLOWS['warm_lead'],
    'cold': WORKFLOWS['cold_lead'],
}


def route(contact_id: str, band: Band) -> str:
    """
    Enroll contact in the right GHL workflow and return the correct pipeline stage ID.
    Returns the stage_id so the caller can set it on the opportunity.
    """
    workflow_id = BAND_WORKFLOW.get(band)
    if workflow_id:
        _enroll_workflow(contact_id, workflow_id)

    stage_id = BAND_STAGE[band]
    logger.info('Routed contact %s → band=%s stage=%s', contact_id, band, stage_id)
    return stage_id


def _enroll_workflow(contact_id: str, workflow_id: str):
    url  = f'{GHL_BASE}/contacts/{contact_id}/workflow/{workflow_id}'
    body = {'eventStartTime': None}
    r = requests.post(url, headers=GHL_HEADERS, json=body, timeout=15)
    if r.ok:
        logger.info('Enrolled %s in workflow %s', contact_id, workflow_id)
    else:
        logger.warning('Workflow enroll failed %s → %s %s', workflow_id, r.status_code, r.text[:200])
