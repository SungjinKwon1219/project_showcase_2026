# AGENTS.md

## Project Overview

This repository is a personalized BAC estimation and drinking-session tracking app.

The product is not just a one-time BAC calculator. The intended product loop is:

Profile input
-> BAC prediction
-> drinking session logging
-> drink/symptom event storage
-> post-session review
-> future Bayesian personalization

The app estimates BAC using a personalized Widmark-style model:

BAC(t) = A / (rW) - beta * t

Where:
- A = grams ethanol consumed
- W = body weight
- r = body water/distribution ratio
- beta = alcohol elimination rate
- t = elapsed time in hours

This app must treat BAC as an estimate, not a legal or medical truth.

Never use language that implies the user is safe to drive.

Preferred wording:
- "estimated BAC"
- "estimated BAC range"
- "lower estimated risk"
- "elevated estimated risk"
- "common legal driving threshold"
- "Estimate only; not legal or medical advice. Do not use this to decide whether to drive."

Avoid:
- "safe"
- "safe to drive"
- "safe range"
- "safe to add"
- "you are sober"
- "below legal limit" as reassurance

## Current Architecture

Important files:

- `BACCalculator.py`
  - Canonical BAC model layer.
  - Contains r estimation, beta scaffolding, BAC calculation, and BAC range calculation.
  - This file should remain the model source of truth.

- `server.py`
  - Lightweight Python HTTP server.
  - Exposes:
    - `POST /predict`
    - `POST /r-coefficient` for compatibility.
  - `/predict` should remain the canonical prediction endpoint.

- `frontend/bac-calculator.html`
  - Main calculator/session logging page.
  - Calls `/predict`.
  - Should not compute authoritative BAC locally.
  - May temporarily contain local graph-preview math, but backend prediction is authoritative.

- `frontend/session-storage.js`
  - Owns localStorage session persistence.
  - Uses:
    - `safer_sessions`
    - `safer_active_session_id`
  - Supports active draft sessions, completed sessions, events, prediction snapshots, and review status.

- `frontend/history.html`
  - Shows real sessions from `safer_sessions`.

- `frontend/dashboard.html`
  - Minimally wired to real recent sessions.
  - Some dashboard cards may still be demo/static and should be clearly labeled if not wired.

- `tests/test_bac_calculator.py`
  - Tests model logic.

- `tests/test_server.py`
  - Tests `/predict` payload logic.

## Canonical Unit Contract

The canonical model/server contract is:

- Alcohol input: grams ethanol
- Weight input: kilograms
- Height input: centimeters
- Time input: hours
- BAC output: display-scale BAC value where `0.08` means “0.08 BAC” / 0.08% BAC
- beta: BAC display units per hour, e.g. `0.015`
- r: dimensionless body-water/distribution ratio

Frontend UI may accept imperial units, but it must normalize before calling `/predict`.

Current frontend conversions:
- pounds -> kilograms
- inches -> centimeters
- standard drinks -> grams ethanol using 14g per standard drink
- time slider -> hours
- body fat bracket is low/mid/high
- body fat percent fallback values may be 12/20/30 for low/mid/high

## Modeling Rules

Do not implement complex ML, reinforcement learning, Q-learning, or PPO.

Do not implement broad Bayesian personalization until the app has enough structured session/feedback data.

For now:
- Keep predictions deterministic.
- Use `estimate_beta(...)` as simple beta scaffolding.
- Current personalization is limited to elimination-rate/beta calibration from high-confidence post-session feedback.
- Feedback is subjective context and is not treated as a ground-truth BAC measurement.
- The app does not currently personalize absorption, body-water distribution (`r`), food effects, drink-size logging error, or impairment interpretation.
- Do not treat symptoms or post-session feedback as exact BAC measurements.
- Symptoms and feedback are subjective context data.

## Current Completed Work

The following has already been implemented:

1. `BACCalculator.py` refactor:
   - Fixed male mid-fat bug.
   - Added canonical `calculate_bac(...)`.
   - Kept deprecated `BACCalculator(...)` wrapper.
   - Added constants:
     - `DEFAULT_BETA_PER_HOUR = 0.015`
     - `DEFAULT_BETA_SD = 0.0025`
     - `MIN_R = 0.45`
     - `MAX_R = 0.80`
     - `MIN_BETA_PER_HOUR = 0.005`
     - `MAX_BETA_PER_HOUR = 0.030`
   - Added validation helpers.
   - Added `estimate_beta(...)`.
   - Added `personalize_beta(...)`.
   - Added `calculate_bac_range(...)`.

2. Backend prediction integration:
   - Added `server.py`.
   - Added `POST /predict`.
   - Kept `POST /r-coefficient`.
   - `/predict` uses:
     - `r_coefficient(...)`
     - `estimate_beta(...)`
     - `calculate_bac_range(...)`
   - Returns explicit units, model info, BAC low/estimate/high, and disclaimer.

3. Frontend prediction integration:
   - `frontend/bac-calculator.html` now calls `/predict`.
   - Removed frontend BAC calculation as source of truth.
   - Removed incorrect `* 100` from temporary graph math.
   - Displays BAC range and backend disclaimer.
   - Persists `prediction_snapshot` into active session.

4. Session logging:
   - `frontend/session-storage.js` supports event-ready sessions.
   - Sessions now support:
     - `title`
     - `events: []`
     - `review_status`
     - `prediction_snapshot`
   - Added/standardized:
     - drink events
     - symptom events
     - active draft session
     - completed session flow

5. History/dashboard:
   - `frontend/history.html` shows real sessions.
   - `frontend/dashboard.html` shows real recent sessions minimally.
   - Some static/demo cards may remain.

## Session Event Model

Drink event shape:

{
  "event_id": "generated-id",
  "event_type": "drink",
  "timestamp": "ISO-8601",
  "standard_drinks": 1,
  "grams_alcohol": 14,
  "label": "1 standard drink"
}

Symptom event shape:

{
  "event_id": "generated-id",
  "event_type": "symptom",
  "timestamp": "ISO-8601",
  "symptom_type": "vomit|heavy_intoxication|blackout_concern|felt_sober|other",
  "severity": 1,
  "notes": ""
}

Symptoms should never directly update BAC/r/beta.

## Current Next Task

The next recommended task is implementing post-session review.

Post-session review should:
- Store subjective feedback.
- Mark completed sessions as reviewed.
- Not call `/predict`.
- Not change beta, r, or BAC predictions yet.
- Prepare structured data for future personalization.

Recommended review shape:

{
  "submitted_at": "ISO-8601",
  "hangover_severity": 0,
  "perceived_peak_intoxication": 0,
  "vomited": false,
  "blackout": false,
  "memory_gap": false,
  "felt_sober_time": "",
  "sleep_hours_after": null,
  "hydration_after": "unknown|low|normal|high",
  "notes": ""
}

A session is pending review if:
- `status` is `"completed"`
- `review_status` is not `"completed"`
- no `post_session_review` exists

## Commands

Run backend:

python3 server.py

Run static frontend from repo root or frontend folder as appropriate:

cd frontend
python3 -m http.server 8000

Be careful: if `server.py` also uses port 8000, do not run both on the same port. Use a different port for static frontend if needed.

Run Python syntax checks:

python3 -m compileall BACCalculator.py server.py tests/test_server.py tests/test_bac_calculator.py

Run backend tests:

python3 -m unittest tests/test_server.py

If pytest is unavailable, use unittest or compileall.

## Coding Rules

- Prefer small, targeted changes.
- Do not redesign the entire UI unless explicitly asked.
- Do not add unnecessary dependencies.
- Preserve backwards compatibility where easy.
- Keep `BACCalculator.py` as the canonical model layer.
- Keep `/predict` backend-authoritative.
- Keep frontend localStorage schema compatible.
- Normalize older sessions via helper functions rather than breaking stored data.
- Return clear implementation reports after changes.