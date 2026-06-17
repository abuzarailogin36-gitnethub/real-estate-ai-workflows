import os
import logging

logger = logging.getLogger(__name__)


def lookup_parcel(address: str) -> dict:
    """
    Enrich a parcel address with Regrid data (zoning, flood zone, acreage, owner).
    Stubbed until REGRID_API_KEY is set — returns empty dict so scoring still runs.

    Once key is available:
      GET https://app.regrid.com/api/v2/parcels/search?query={address}&token={key}
    Useful fields: ll_gisacre, zoning, zoning_description, dpv_status, fema_flood_zone
    """
    api_key = os.getenv('REGRID_API_KEY', '')
    if not api_key:
        logger.debug('REGRID_API_KEY not set — parcel enrichment skipped')
        return {}

    # TODO: implement when key is available
    return {}
