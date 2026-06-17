from dataclasses import dataclass
from typing import Literal

Band = Literal['hot', 'warm', 'cold']


@dataclass
class ScoreResult:
    fit: int
    intent: int
    total: int
    band: Band


def score(answers: dict) -> ScoreResult:
    """
    Pure scoring function — no I/O, safe to unit-test in isolation.

    answers keys (all optional):
        parcel_address, persona, need, timeline, site_stage,
        acreage, name, phone, email

    persona values : owner | broker | builder | investor
    need values    : sell | subdivide | build | value | jv
    timeline values: now | 3mo | 6-12mo | exploring
    site_stage     : raw | partially_improved | shovel_ready
    """
    fit = 0
    intent = 0

    persona    = answers.get('persona', '')
    need       = answers.get('need', '')
    timeline   = answers.get('timeline', '')
    site_stage = answers.get('site_stage', '')

    # ── Fit (who are they) ───────────────────────────────────────────────────
    if answers.get('parcel_address') or answers.get('acreage'):
        fit += 20   # owns / has a specific site
    if persona in ('owner', 'builder'):
        fit += 20   # decision-maker / principal (not an intermediary)
    if persona == 'builder' and site_stage == 'shovel_ready':
        fit += 20   # builder seeking ready lots — highest-value persona
    if persona in ('owner', 'builder', 'investor'):
        fit += 15   # matches ICP
    if persona == 'investor':
        fit += 10   # capital partner

    # ── Intent (how ready) ───────────────────────────────────────────────────
    if timeline in ('now', '3mo'):
        intent += 25   # near-term — will act
    if answers.get('parcel_address'):
        intent += 20   # submitted a specific parcel (not just browsing)
    if need in ('build', 'subdivide'):
        intent += 20   # action-oriented need, not "just find value"
    if answers.get('name') and answers.get('phone'):
        intent += 15   # completed the full quiz

    # +15 "replied / asked a question" is applied later by conversation engine

    fit    = min(fit, 50)
    intent = min(intent, 50)
    total  = fit + intent

    band: Band = 'hot' if total >= 70 else ('warm' if total >= 40 else 'cold')
    return ScoreResult(fit=fit, intent=intent, total=total, band=band)
