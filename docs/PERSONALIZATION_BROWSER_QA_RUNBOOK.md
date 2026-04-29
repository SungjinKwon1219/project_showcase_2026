# Manual browser QA runbook — personalization (v1)

Use this document to run **interactive** QA for `input.html`, `bac-calculator.html`, `history.html`, and `dashboard.html` with `localStorage`, `POST /predict`, and `POST /implied-beta`.

For **automated** helpers and Node simulation, see **`PERSONALIZATION_E2E_QA.md`**. For **reset/delete controls**, see **`PERSONALIZATION_DATA_CONTROLS.md`**.

---

## 1. Environment: exact commands

### 1.1 Backend (BAC API)

From the **repository root**:

```bash
cd /path/to/project_showcase_2026
python3 server.py
```

**Expected output** (or similar):

```text
BAC API listening at http://0.0.0.0:8000
```

- **Base URL for the browser on this machine:** `http://localhost:8000`
- **Endpoints used by this app:**
  - `POST http://localhost:8000/predict` — calculator
  - `POST http://localhost:8000/implied-beta` — history feedback save path

The handler sets **`Access-Control-Allow-Origin: *`** so the UI can load from another origin/port.

### 1.2 Frontend (static HTML/JS/CSS)

Serve the **`frontend/`** directory with a **different port** than the API (avoid binding two servers to **8000**).

From **`frontend/`**:

```bash
cd /path/to/project_showcase_2026/frontend
python3 -m http.server 8080
```

**Open in the browser:** `http://localhost:8080/bac-calculator.html`  
(Use **`8080`** or any free port consistently in this doc; adjust if yours differs.)

### 1.3 Why two ports?

- **`server.py`** listens on **`8000`** by default (`HOST=0.0.0.0`, `PORT=8000` in `server.py`).
- Static files should not share **8000** with the API in the usual dev setup.

---

## 2. Verify API wiring (calculator & history)

| Location | Constant / URL |
|----------|----------------|
| **`frontend/bac-calculator.html`** | `const API = 'http://localhost:8000/predict'` (inline script, near top of main script block) |
| **`frontend/history.html`** | `fetch('http://localhost:8000/implied-beta', ...)` |

**Before QA:** Confirm these match your running API (`http://localhost:8000`). If you run the API on another host/port, change both files **temporarily for local QA only** or use a tunnel; do not commit stray URLs unless the project adopts a shared config.

**Quick API check** (backend running):

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"profile":{"sex":"male","age_years":30,"height_cm":175,"weight_kg":70,"body_fat_percent":20,"drinks_per_week":4},"session":{"grams_alcohol":14,"hours_elapsed":1}}'
```

Expect **200** and JSON with `bac`, `personalization`, etc.

---

## 3. Browser and localStorage

### 3.1 Preferred setup

- **Use HTTP**, not `file://`, so behavior matches normal deployment and storage is consistent.
- **Origin** for pages: `http://localhost:8080` (if using the static server above).
- **localStorage** is **per origin** (scheme + host + port).

### 3.2 Clear storage (clean run)

1. Open DevTools → **Application** (Chrome) or **Storage** (Firefox).
2. Under **Local Storage** → `http://localhost:8080`, delete keys  
   **`safer_sessions`**, **`safer_active_session_id`**, **`safer_user_profile`**, **`safer_personalization_settings`**, or use **Clear site data**.
3. Hard refresh the tab (`Cmd+Shift+R` / `Ctrl+Shift+R`).

### 3.3 Preserve storage (persistence tests)

1. Do **not** clear site data between steps **within** the same origin.
2. To test **refresh**, use normal reload (**F5** / **Cmd+R**).
3. To test **cold start**, optionally close tab and reopen the same origin URL — keys should persist.

---

## 4. Seeded localStorage fixtures (DevTools snippets)

Paste in **Console** on `http://localhost:8080/...` (**Application** panel can also paste raw JSON **per key**).

**Keys used by the app:**

| Key | Purpose |
|-----|---------|
| `safer_user_profile` | Baseline profile JSON |
| `safer_sessions` | Array of session objects |
| `safer_active_session_id` | Active draft session id (optional) |
| `safer_personalization_settings` | Toggle + defaults |

### 4.1 Empty state

```javascript
localStorage.removeItem('safer_sessions');
localStorage.removeItem('safer_active_session_id');
localStorage.removeItem('safer_user_profile');
localStorage.removeItem('safer_personalization_settings');
location.reload();
```

### 4.2 Profile only (minimal valid shape — adjust fields to match UI)

```javascript
localStorage.setItem('safer_user_profile', JSON.stringify({
  name: 'QA User',
  sex: 'male',
  age_years: 30,
  height_cm: 175,
  weight_kg: 70,
  body_fat_percent: 18,
  drinks_per_week: 4
}));
location.reload();
```

### 4.3 Personalization disabled (Dashboard toggle)

```javascript
localStorage.setItem('safer_personalization_settings', JSON.stringify({
  schema_version: 1,
  limited_personalization_enabled: false,
  save_feedback_enabled: true,
  updated_at: new Date().toISOString()
}));
location.reload();
```

### 4.4 Usable / unusable calibration (illustrative)

Full session objects are **large**; for layout-only checks, prefer **driving the real UI** (History feedback + `/implied-beta`) so `implied_beta_result` matches server rules. For a **minimal** sanity object, inspect a real saved session **Export** / DevTools → copy **`safer_sessions`** from a healthy run once, then reuse as a baseline.

---

## 5. Numbered test cases

Record results in **[Section 8 — QA result template](#8-qa-result-template)**.

### Group A — Profile setup

| ID | Test case | Steps (summary) | Expected |
|----|-----------|-----------------|----------|
| A1 | Empty profile banner | Clear storage; open Dashboard | Shows “no profile” / call-to-action without console errors |
| A2 | Save profile | `input.html` → fill baseline → save | Redirect or confirm save; **`safer_user_profile`** populated |
| A3 | Dashboard reflects profile | Open Dashboard | Baseline Profile shows **Complete** (or equivalent) |

### Group B — Calculator prediction

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| B1 | Prediction with API | Backend on **8000**; open Calculator from **`http://localhost:8080`**; start session, log drink, Update Estimate | Estimated BAC + range; no network CORS failure |
| B2 | Personalization status strip | Same | Status card shows limited personalization messaging; no crash |
| B3 | BAC band label | View zone legend | Lowest band shows **Lower estimate range** — not **Safe** |

### Group C — High-confidence feedback

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| C1 | Complete session | End session from calculator flow | Session **completed** in History |
| C2 | Usable metadata | History → completed session → fill high-confidence fields (missed=no, timing/log high; plausible hours); save | Feedback saved; **`/implied-beta`** returns usable payload when gated fields pass |

### Group D — Rejected feedback

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| D1 | Gated rejection | Same form with blackout OR missed drinks OR low timing confidence → save | Feedback still saved **subjective** rows; calibration **unusable** with rejection reasons |

### Group E — Dashboard personalization

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| E1 | Limited personalization card | Open Dashboard | One-line status, **Feedback saved** / **Usable calibration signals**, **Next best action**, **Apply limited personalization** checkbox visible without expanding details |
| E2 | Next best action | With/without feedback | Guidance block fills |
| E3 | Reliability (expand **Reliability detail**) | Toggle section open | Badge + narrative; optional factor lines |
| E4 | Evidence (expand **Calibration signal by session**) | Compare **Used / Not used / No signal** to rows | Counts reconcilable with visible list |
| E5 | History link | Expand evidence section → click **History →** | Opens `history.html` |
| E6 | Empty state | Fresh profile, no sessions (and toggle off/on) | Short, readable messaging; toggling **Apply limited personalization** refreshes status line |

### Group F — Settings toggle

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| F1 | Toggle off | Dashboard → uncheck limited personalization → refresh | Toggle stays off; **`safer_personalization_settings`** has `limited_personalization_enabled: false` |
| F2 | `/predict` when off | Calculator → estimate | Response `personalization.active === false`, `disabled_by_user === true`, `effective_beta` matches `base_beta` (inspect DevTools Network) |
| F3 | Toggle on | Dashboard → enable → Calculator estimate | Calibration can affect effective beta again when usable history exists |

### Group G — Reset/delete controls

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| G1 | Confirm cancel | Each control → **Cancel** | No change to storage |
| G2 | Reset settings only | Confirm reset settings | Toggle/defaults restored; sessions intact |
| G3 | Clear calibration | Confirm | **`implied_beta_result`** stripped from feedback; subjective text remains |
| G4 | Clear snapshots | Confirm | Stripped personalization from **`prediction_snapshots`** |
| G5 | Clear all | Confirm | Matches **`PERSONALIZATION_DATA_CONTROLS.md`** |

### Group H — After resets

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| H1 | Calculator | Run estimate after resets | Page works; metadata matches current helpers |
| H2 | History | Reload History | Sessions list intact unless individually deleted |

### Group I — Refresh / persistence

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| I1 | Dashboard toggle persistence | Toggle → reload | State preserved |
| I2 | Session list | Add session → reload | Persisted |

### Group J — Responsive layout

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| J1 | Desktop | Full-width window | No overlapping fixed sidebar |
| J2 | Narrow | Resize to ~375px wide | Sidebar/cards/buttons usable; personalization buttons wrap |
| J3 | History layout | **history.html** at desktop | Four metric cards align with the row below: session **list** spans first two columns, detail/feedback panel spans last two (equal width); session cards stack fields without relying on horizontal scroll |
| J4 | History stacked | **history.html** ~1100px then ~700px | Main row stacks to two columns then single column without clipping |

### Group K — Copy / safety scan

| ID | Test case | Steps | Expected |
|----|-----------|-------|----------|
| K1 | Risky phrases | Read visible strings on all four pages | No **safe to drive**, **you are sober**, user-facing BAC band **Safe**, unjustified accuracy claims |

---

## 8. QA result template

Copy this table for each manual run (`RUN-YYYYMMDD-initials`).

| TC ID | Steps executed | Expected (short) | Actual | Pass/Fail | Screenshot / notes file | Severity (S0–S3) | Likely files |
|-------|----------------|------------------|--------|-----------|--------------------------|-----------------|--------------|
| A1 | | | | | | | |
| A2 | | | | | | | |
| *(add rows)* | | | | | | | |

**Severity:** S0 = blocker crash/data loss · S1 = major wrong behavior · S2 = polish · S3 = doc/nit  

---

## 9. Risks / TODOs

- **Port mismatch:** If **`server.py`** is changed to non-8000 without updating **`bac-calculator.html`** / **`history.html`**, predictions and implied-beta fail.
- **HTTPS mix:** Serving UI on **`https`** and API on **`http`** may trigger mixed-content blocks — keep both **`http`** for local QA unless you add HTTPS to the API.
- **Evidence counts** must be checked against **`getPersonalizationEvidenceRows`** expectations after real feedback (fixtures are illustrative).

---

## 10. Validation (repo, after doc-only changes)

Optional:

```bash
node --check frontend/session-storage.js
node tests/test_session_storage_helpers.js
python3 -m unittest tests/test_server.py tests/test_bac_calculator.py tests/test_bayesian_stats.py tests/test_reversebeta.py
```
