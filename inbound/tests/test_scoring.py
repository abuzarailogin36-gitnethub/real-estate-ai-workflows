import sys
sys.path.insert(0, '/tmp/real-estate-ai-workflows')
from inbound.scoring import score


def test_hot_owner_with_parcel_and_urgent_timeline():
    r = score({
        'parcel_address': '123 Main St, Denton TX',
        'persona': 'owner',
        'need': 'subdivide',
        'timeline': 'now',
        'name': 'John Doe',
        'phone': '+12145551234',
    })
    assert r.band == 'hot'
    assert r.total >= 70


def test_hot_builder_shovel_ready():
    r = score({
        'parcel_address': '100 Builder Blvd, Collin TX',
        'persona': 'builder',
        'site_stage': 'shovel_ready',
        'need': 'build',
        'timeline': '3mo',
        'name': 'Builder Bob',
        'phone': '+12145550001',
    })
    assert r.band == 'hot'


def test_warm_owner_no_parcel_long_timeline():
    # Owner who hasn't submitted a parcel yet and is 6-12mo out
    # fit: +20 (owner) +15 (ICP) = 35; intent: +15 (full quiz) = 15; total 50 → warm
    r = score({
        'persona': 'owner',
        'need': 'value',
        'timeline': '6-12mo',
        'name': 'Jane Smith',
        'phone': '+12145559876',
    })
    assert r.band == 'warm'
    assert r.total == 50


def test_cold_broker_no_parcel_no_timeline():
    r = score({
        'persona': 'broker',
        'need': 'value',
        'timeline': 'exploring',
    })
    assert r.band == 'cold'


def test_cold_empty_answers():
    r = score({})
    assert r.band == 'cold'
    assert r.total == 0
    assert r.fit == 0
    assert r.intent == 0


def test_fit_capped_at_50():
    # owner + parcel + builder-shovel_ready + ICP match + investor = 85 raw fit
    r = score({
        'persona': 'builder',
        'parcel_address': '789 Elm St',
        'site_stage': 'shovel_ready',
    })
    assert r.fit <= 50


def test_intent_capped_at_50():
    r = score({
        'timeline': 'now',
        'parcel_address': '789 Elm St',
        'need': 'build',
        'name': 'Bob',
        'phone': '+1234567890',
    })
    assert r.intent <= 50


def test_investor_warm_no_parcel():
    r = score({
        'persona': 'investor',
        'need': 'jv',
        'timeline': '6-12mo',
        'name': 'Carol',
        'phone': '+12145553333',
    })
    # fit: +15 (ICP) + +10 (investor) = 25; intent: +15 (full quiz) = 15; total 40
    assert r.band in ('warm', 'hot')
    assert r.total >= 40


def test_score_result_fields():
    r = score({'persona': 'owner', 'parcel_address': '1 Main', 'timeline': 'now',
               'need': 'build', 'name': 'X', 'phone': '+10000000000'})
    assert 0 <= r.fit <= 50
    assert 0 <= r.intent <= 50
    assert r.total == r.fit + r.intent
    assert r.band in ('hot', 'warm', 'cold')
