#!/usr/bin/env python3
"""Weekly Friday 5pm CT KPI report → Slack #quizwarmleads."""
import logging
import os
import sys
sys.path.insert(0, '/opt/newdoor/scripts')

# Load Hermes .env so SLACK_ALERTS_CHANNEL etc. are available
_ENV = '/root/.hermes/.env'
if os.path.exists(_ENV):
    for line in open(_ENV):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s — %(message)s',
)

from inbound.summary import run_weekly_report

if __name__ == '__main__':
    run_weekly_report()
