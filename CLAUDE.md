# Handoff — Inbound Lead Engine (Tier 1) for Claude Code

**Project:** New Door Investments — inbound-only lead generation + automation engine
**Owner:** Mir M. Ali (DFW land developer & consultant). Team: Mir + offshore VA + onsite resource.
**This doc:** a self-contained brief to build the **Tier 1** automation in Claude Code. Captures all decisions from the planning session so you don't need prior context.
**Date:** 2026-06-16

---

## 1. Goal (what we're building)

An automated, server-side inbound lead engine where prospects self-select via a **Feasibility Quiz**, get **scored and routed by Hermes** (the cloud agent), land in **GoHighLevel (GHL)**, are nurtured automatically, and produce **one Slack ping** to Mir when a hot lead books a call. Tier 1 turns on the three warmest channels first.

**Tier 1 channels (all drive to ONE destination — the quiz):**
1. **Referral partner network** — brokers, builders, civil engineers, land-use attorneys, surveyors, title companies. Each gets a **unique quiz link** + a finder fee on closed deals. (Fastest source — build attribution for it.)
2. **LinkedIn organic** — Mir's personal brand, 5 posts/week, each with a soft CTA to the quiz. (Attribution via UTM links.)
3. **Existing / capital network** — HNW IT + doctor contacts as capital partners + consulting clients, via content + direct links.

**Out of scope for Tier 1 (later tiers):** Google Search ads, retargeting, SEO site, lead-magnet checklist.

---

## 2. Non-negotiable constraints

- **Inbound / opt-in only. NO cold calling, NO cold texting, NO cold email blasts.** (TCPA + the owner abandoned cold outreach — it failed.) SMS only to leads who checked an opt-in box.
- **Offer = free feasibility call first.** Do NOT quote prices in automation. Priced tiers ($750 Land Screen / $2,500 Full DD / $5,000 Builder-Ready / JV) exist but are introduced manually later.
- **Hermes owns the brain:** scoring, orchestration, live SMS/chat conversation, and booking. GHL = system of record + channels. Slack = human handoff.
- **Positioning:** Mir is a developer/consultant/JV partner, NOT a cash wholesaler. Tone: operator-to-operator, value-first, never pushy.

---

## 3. Architecture

```
ATTRACT  (referral links / LinkedIn UTM / capital-network links)
   |
   v
QUIZ  (GHL-native survey/funnel; 7 steps; returns instant snapshot teaser)
   |  on submit -> webhook
   v
HERMES  (cloud server, 24/7)  -- the brain
   |- enrich parcel via Regrid API
   |- score Fit x Intent (0-100)
   |- write score/fields/tags back to GHL
   |- route: >=70 book + Slack alert / 40-69 nurture / <40 self-serve
   |- own live SMS/chat replies + booking
   |- post hot-lead handoff + daily/weekly summaries to Slack
   |
   v
GHL  (contacts, opportunities in "Land Development Consulting" pipeline, nurture workflows, calendar)
   |
   v
SLACK  ->  Mir takes the booked call (Fathom logs notes)
```

**Component ownership:**
- **Code (build in Claude Code, deploy to Hermes server):** webhook receiver, scoring engine, GHL client, Regrid client, Slack client, referral attribution service, scheduled summary jobs.
- **GHL config (no code, done in GHL UI by VA):** the quiz survey/funnel, nurture workflows, calendar. The webhook *action* that calls Hermes is configured in a GHL workflow.

---

## 4. Integrations & environment

Create a `.env` (do not commit). Confirm exact values with Mir.

```
# GoHighLevel
GHL_API_KEY=            # GHL private integration / API token (location-scoped)
GHL_LOCATION_ID=wnvEXpw2cKL1z3DwfQB8
GHL_PIPELINE_ID=c3E4r3zxrMsRihshKWSx        # "Land Development Consulting"
GHL_STAGE_NEW_LEAD=18ed601a-f682-4dcf-a291-cef15b01a86e
GHL_CALENDAR_ID=        # Mir's booking calendar (confirm)

# Regrid (parcel enrichment)
REGRID_API_KEY=

# Slack
SLACK_BOT_TOKEN=
SLACK_CHANNEL_ALERTS=   # e.g. #hot-leads  (confirm channel)

# Hermes
HERMES_BASE_URL=        # confirm how Hermes exposes itself (HTTP API / MCP)
HERMES_AUTH=
```

**GHL location facts (verified):** name "New Door", timezone US/Central, `allowDuplicateContact=false`, unique identifier = **phone**. Workflows, conversations, calendars, AI features all enabled.

**GHL pipeline stages (Land Development Consulting):**
`New Lead (18ed601a...)` -> `Attempting Contact (9c33580b...)` -> `Contacted Not Ready (e80f1cc7...)` -> `Warm Considering (53b527b8...)` -> `Appointment Set (bdbd3f9e...)` -> `Active Deal (122b4540...)` -> `Dead/DNC (ea89de3c...)`.

> NOTE: Confirm whether Hermes already has GHL / Regrid / Slack credentials wired. If so, reuse them rather than duplicating.

---

## 5. The Feasibility Quiz (capture surface)

7 steps, ~90 seconds. Built GHL-native first; a custom Regrid-powered web app is a later upgrade. Each answer maps to a CRM field and feeds scoring.

| # | Question | Field | Type |
|---|----------|-------|------|
| 1 | Property address or county | `parcel_address` | text |
| 2 | Owner / broker / builder-developer? | `persona` | enum |
| 3 | Sell / subdivide / build / just find value? | `need` | enum |
| 4 | How soon? (now / 3mo / 6-12mo / exploring) | `timeline` | enum |
| 5 | Raw / partially improved / shovel-ready? | `site_stage` | enum |
| 6 | Acreage / size | `acreage` | number |
| 7 | Name + email + phone (+ SMS opt-in checkbox) | `contact` | contact |

**On submit:** GHL workflow fires a webhook to Hermes with all answers + contact info. Hermes immediately (a) returns/sends the instant snapshot teaser, (b) enriches + scores, (c) writes back.

**Instant snapshot teaser content (auto):** likely zoning considerations, "what owners in {county} typically build", the 3 paths (sell as-is / subdivide / JV-to-build), CTA to book the free call. Polished one-page Land ID snapshot is produced manually by Mir within 2-3 business days.

---

## 6. Scoring — Fit x Intent (0-100)

| Fit (who) | Pts | Intent (ready) | Pts |
|---|---|---|---|
| Owns developable land / has a site | +20 | Timeline now / <3 mo | +25 |
| Decision-maker / principal | +20 | Submitted a specific parcel | +20 |
| Builder/dev seeking shovel-ready lots | +20 | Need = build/subdivide (not just curious) | +20 |
| Persona matches ICP | +15 | Completed full quiz (vs bounced) | +15 |
| Capital partner / institutional | +10 | Replied / asked a question | +15 |

**Bands -> route:**
- **70+ = HOT** -> Hermes offers 2 calendar slots, books, moves opportunity to `Appointment Set`, posts Slack alert.
- **40-69 = WARM** -> enroll in nurture (tag `nurture-owner` or `nurture-investor`), stage `Warm Considering`.
- **<40 = COLD** -> self-serve content track, light touch.

Implement scoring as a pure, unit-tested function: `score(answers) -> { fit, intent, total, band }`.

---

## 7. Data model

**Contact (GHL custom fields):** `parcel_address`, `persona`, `need`, `timeline`, `site_stage`, `acreage`, `lead_score`, `fit_score`, `intent_score`, `band`, `referral_partner`, `source`, `sms_optin` (bool).

**Tags:** `inbound`, `feasibility-quiz`, `source:{referral|linkedin|capital|website}`, `persona:{owner|broker|builder|investor}`, `goal:{sell|subdivide|build|value|jv}`, `band:{hot|warm|cold}`, `partner:{CODE}`.

**Opportunity:** created in pipeline `GHL_PIPELINE_ID`, name `"{city/county} - {acreage}ac - {need}"`, stage per band.

**Referral ledger (Hermes DB/table):** `partner_code`, `partner_name`, `partner_type`, `quiz_link`, `leads_count`, `booked_count`, `deals_closed`, `fee_owed`, `fee_paid`.

---

## 8. Build backlog (ordered)

**Milestone 1 — Core capture->score->route loop**
1. `POST /webhooks/quiz` receiver (validate payload, idempotent on contact phone).
2. Regrid client: `lookupParcel(address|apn)` -> zoning/flood/area context.
3. Scoring module (section 6) + unit tests.
4. GHL client: upsert contact + custom fields + tags; create/update opportunity + stage.
5. Routing logic (hot/warm/cold) writing the right stage + tags.
*Acceptance:* a posted dummy submission creates the correct contact, fields, tags, opportunity, and band in GHL.

**Milestone 2 — Slack handoff**
6. Slack client: post hot-lead alert to `SLACK_CHANNEL_ALERTS` with name, persona, parcel, answers, score, Hermes summary, and booking time.
*Acceptance:* a 70+ dummy lead produces a correctly formatted Slack message.

**Milestone 3 — Booking + conversation (Hermes-owned)**
7. Booking: offer 2 free slots from `GHL_CALENDAR_ID`, confirm, move to `Appointment Set`.
8. Live conversation handler (SMS/chat) per the Hermes persona prompt (operator tone, never quote price, honor opt-out instantly).
*Acceptance:* hot dummy lead can be booked end-to-end; opt-out stops messaging immediately.

**Milestone 4 — Referral attribution (Tier 1's edge)**
9. Partner registry + `generateQuizLink(partnerCode)` (e.g., `.../quiz?ref=CODE`).
10. Capture `ref` on submission -> set `referral_partner` + `partner:{CODE}` tag -> increment ledger.
11. Ledger updates on booking + closed deal -> compute `fee_owed`.
*Acceptance:* a submission via a partner link is attributed and shows in the ledger.

**Milestone 5 — Scheduled summaries (server cron, replaces laptop-dependent jobs)**
12. Daily 7am CT: lead summary -> Slack.
13. Weekly Fri: KPI report (section below) -> Slack.

**Later (note, don't build yet):** migrate the existing outbound "Daily Lead Robot" (Apify LandWatch scrape -> score -> GHL) onto Hermes cron; Google Ads/retargeting/SEO attribution; custom quiz web app.

---

## 9. KPIs to expose (for the weekly Slack report)

Quiz starts -> completions (%), leads/week, % auto-qualified (target >90%), hot (70+)/week, auto-booked calls/week, request->booked rate, source breakdown (referral vs LinkedIn vs capital), referral leads + fees owed. North star: signed deals/retainers.

---

## 10. Open questions to resolve first (ask Mir)

1. **Hermes interface:** HTTP API or MCP? Base URL + auth? What language/framework is she built in (so code matches the repo)?
2. **What's already wired into Hermes:** Regrid key? GHL token? Slack token? (Reuse, don't duplicate.)
3. **Slack:** which workspace + channel for alerts/summaries?
4. **GHL:** confirm API token + the booking calendar ID; confirm/create the custom fields in section 7.
5. **Quiz build:** confirm GHL-native quiz (recommended) for v1 vs custom web app.

---

## 11. Key decisions log (context captured from planning)

- Pivoted from outbound (PropStream + cold text/email) — it failed (saturation, dirty data, too few touches, wrong positioning, TCPA risk). Cold texting killed; PropStream paused (reactivate per-campaign only for direct mail if ever needed).
- **Land ID** kept as the deep-dive DD tool and the engine of the feasibility offer. **Regrid** added as the bulk parcel-data/API layer for automation/enrichment (different job than Land ID).
- Reviewed competing Gemini (outbound) and Perplexity (inbound) plans. Adopted from them: the **Feasibility Quiz centerpiece**, **Fit x Intent scoring**, **channel-to-one-destination** discipline, **referral finder-fee loop**, **TBD/unplatted/ag-exempt/infill/surplus-municipal targeting**, and **referral + capital-partner audiences**. Rejected: cold SMS/voicemail drops (TCPA), redundant second-AI "Gems".
- Brain decision: **Hermes owns everything** (orchestration + live conversation + booking + Slack handoff), running 24/7 on the cloud server so it never depends on Mir's laptop.
- Companion reference doc (full marketing detail — LinkedIn profile, 10 posts, nurture copy, build order): `docs/Inbound_Lead_Engine_BuildPack.md`.
