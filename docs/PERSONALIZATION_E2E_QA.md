# Personalization End-to-End QA v1

This checklist verifies the Safer BAC **limited elimination-rate personalization** loop (frontend localStorage → `/predict` → History feedback → `/implied-beta` metadata). Full browser automation for this repo is optional; **`tests/test_session_storage_helpers.js`** includes a scripted simulation of helpers and persistence.

**Interactive manual browser QA (ports, URLs, numbered cases, templates):** **`docs/PERSONALIZATION_BROWSER_QA_RUNBOOK.md`**.

**Reset/delete controls** (Dashboard + `SaferSessionStorage`): see **`docs/PERSONALIZATION_DATA_CONTROLS.md`**.

## Prerequisites

- Backend API running (**default:** `python3 server.py` → **`http://localhost:8000`** — see **`PERSONALIZATION_BROWSER_QA_RUNBOOK.md`** for serving static files on another port).
- Static frontend served (e.g. `python3 -m http.server 8080` from `frontend/` — **do not** bind static server to **8000** while API uses **8000**).
- **`frontend/bac-calculator.html`** and **`frontend/history.html`** use **`localhost:8000`** for **`/predict`** and **`/implied-beta`**; change only if your API differs.

## Scripted scenario (Node)

Run:

```bash
node tests/test_session_storage_helpers.js
```

Look for blocks labeled **`E2E simulation`** (profile + completed session + usable feedback snapshot + toggle persistence).

## Scenario narrative

1. **Profile** exists (`safer_user_profile`) with baseline fields sufficient for calculator `/predict`.
2. User completes a drinking session (**History** shows `completed`).
3. User submits **high-confidence** feedback (missed drinks `no`, log/timing `high`, no blackout/vomit/memory gap; plausible near-baseline timing). **Save feedback.**
4. **`/implied-beta`** returns `usable_for_personalization: true` and an implied beta (History shows calibration usable).
5. **History** detail: feedback saved; **usable** path shows calibration signal / beta metadata only when explicitly usable.
6. **Calculator** computes with `history.session_implied_betas` populated from gated entries only; **`/predict`** returns `personalization.active: true` when evidence shifts effective β away from base (subject to demographics).
7. **Dashboard**: **Limited personalization** card shows counts (feedback + usable calibration signals) and collapsible sections for reliability, calibration-by-session list, technical snapshot; **Next best action** updates conservatively.

### Dashboard toggle (limited personalization OFF)

8. Dashboard: turn **Apply limited personalization in BAC estimates** **off**.
9. **`safer_personalization_settings`** stores `limited_personalization_enabled: false`. Refresh Dashboard: toggle stays off.
10. **Calculator**: next `/predict` includes `personalization_settings.limited_personalization_enabled: false`. Response: `personalization.active: false`, `disabled_by_user: true`, `effective_beta` equals **`base_beta`**, totals still visible in summary.

**Important:** Turning the toggle **off does not erase** History feedback or usable implied-beta rows in storage. Existing **prediction snapshots** on old sessions **still show** whichever metadata was captured at prediction time until the user computes again.

### Toggle back ON

11. Toggle **on**, run **Update Estimate** (or wait for auto-refresh during an active session). `/predict` may again blend usable signals; `effective_beta` may diverge from `base_beta`.

## Browser / manual QA checklist

### Dashboard

| Step | Expected |
|------|----------|
| Open Dashboard with data | **Limited personalization** loads; headline counts + empty states render without errors |
| Calibration signal by session (expand) | Rows or dashed empty-state; Used / Not used / No signal counts reconcile |
| Reliability detail (expand) | Label + narrative; factors list when helpers provide them |
| Settings toggle ON | Checkbox checked by default first visit; helper text distinguishes baseline estimate vs calibration signal adjustment |
| Toggle OFF → reload | Toggle remains OFF (`safer_personalization_settings`) |
| Toggle ON → reload | Toggle remains ON |

### BAC Calculator

| Step | Expected |
|------|----------|
| With profile + usable history | Status can show limited personalization active when API reports `active` |
| Reliability snippet | Matches helper label (Transparency only) |
| After toggle OFF | Status indicates personalization turned off; baseline elimination assumption; hints that signals may remain saved |

### History

| Step | Expected |
|------|----------|
| Saved feedback visible | Subjective fields + calibration status lines |
| Unusable gated feedback | Rejection reasons readable; feedback still saved |
| Usable calibration | Explicit usable metadata only when `usable_for_personalization === true` |

## Legacy `implied_beta` (no `implied_beta_result`)

Session feedback that only has a bare numeric `implied_beta` **without** `usable_for_personalization: true` on `implied_beta_result`:

- **Must not** appear in `getAllImpliedBetas()` (so the **browser** does not send it to `/predict`).
- **Must not** count as usable evidence in Profile / Evidence / Reliability helpers.

**API note:** The server still accepts **raw numbers** in `history.session_implied_betas` for backward compatibility with older clients. The product’s browser path uses gated objects from storage only.

## Copy / safety (spot check)

Avoid reassuring driving or medical language. The calculator labels the lowest displayed BAC band **“Lower estimate range”** (estimated visualization only, not driving or medical safety).
