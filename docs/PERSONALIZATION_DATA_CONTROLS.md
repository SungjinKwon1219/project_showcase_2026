# Personalization data controls (local device)

All controls run in the **browser** (`localStorage` on this device). They do **not** change server logic, `/implied-beta` gating, or calibration math.

**Interactive browser QA:** see **`docs/PERSONALIZATION_BROWSER_QA_RUNBOOK.md`** for ports, **`localStorage`** keys, and numbered test groups.

## API (`SaferSessionStorage` in `frontend/session-storage.js`)

| Helper | What it does | What it does not do |
|--------|----------------|---------------------|
| `clearPersonalizationSettings()` | Removes the `safer_personalization_settings` key. Next read behaves like defaults. | Does not delete sessions, feedback, or snapshots. |
| `resetPersonalizationSettingsToDefault()` | Writes explicit defaults (`limited_personalization_enabled: true`, `save_feedback_enabled: true`). | Same as above. |
| `clearPersonalizationPredictionSnapshots()` | For every session, strips `personalization_summary` and `response_payload.personalization` from `prediction_snapshot` / `prediction_snapshots`. | Does not remove BAC/curve fields in snapshots. Does not delete feedback or sessions. |
| `clearCalibrationEvidence()` | For each session with feedback, removes `implied_beta_result` and clears legacy `implied_beta`, then re-normalizes the review. Only updates rows that had calibration fields. | Keeps subjective fields (notes, confidence, symptoms, etc.). Does not delete sessions or profile. |
| `clearAllPersonalizationData()` | Calls snapshot strip, then calibration clear, then `resetPersonalizationSettingsToDefault()`. | Does not delete session list, events, or profile. **Does not delete subjective feedback text.** |

### Limitations

- **Legacy API clients** could still POST raw numeric `session_implied_beta` history; this doc covers the **Safer web app** storage path only.
- **Calculator UI** shows cached personalization text until the **next** `/predict` response updates the screen.
- Unmarked legacy `implied_beta` on old feedback was never treated as usable calibration; clearing calibration removes it explicitly.

## Dashboard UI

Under **Manage local personalization data** (**Limited personalization** section on `dashboard.html`, expandable):

1. **Reset settings** — `resetPersonalizationSettingsToDefault()` + confirm.
2. **Clear prediction personalization snapshots** — `clearPersonalizationPredictionSnapshots()` + confirm.
3. **Clear calibration evidence from feedback** — `clearCalibrationEvidence()` + confirm.
4. **Clear all personalization data** — `clearAllPersonalizationData()` + confirm.

Each action uses `window.confirm()` before running, then refreshes profile/evidence/reliability/metrics on the Dashboard.

## Manual QA checklist

1. With sample data, open Dashboard → confirm four buttons appear and each confirm dialog matches the action.
2. After **Clear calibration evidence**, open History → subjective feedback still visible; calibration lines gone or “no signal.”
3. After **Clear snapshots**, Dashboard “latest” personalization may show no metadata until new predictions exist.
4. After **Reset settings**, **Apply limited personalization in BAC estimates** returns to default (on).
5. Reload page — settings and data changes persist as expected.

The main **Limited personalization** card shows a short summary, next-best action, and the **Apply limited personalization in BAC estimates** checkbox by default. Reliability narrative, calibration-by-session list, technical β snapshot, and data controls stay in expandable subsections until opened.

See also `docs/PERSONALIZATION_E2E_QA.md` for the broader personalization loop.
