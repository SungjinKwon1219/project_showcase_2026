const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function loadStorage() {
  const store = {};
  const sandbox = {
    console,
    localStorage: {
      getItem: (key) => Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null,
      setItem: (key, value) => { store[key] = String(value); },
      removeItem: (key) => { delete store[key]; },
    },
    crypto: { randomUUID: () => 'test-id-' + Math.random().toString(36).slice(2) },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(fs.readFileSync('frontend/session-storage.js', 'utf8'), sandbox);
  return { S: sandbox.SaferSessionStorage, store };
}

function completedSession(overrides) {
  return Object.assign({
    schema_version: 2,
    session_id: 'session-1',
    status: 'completed',
    started_at: '2026-04-28T00:00:00.000Z',
    updated_at: '2026-04-28T00:00:00.000Z',
    events: [],
    post_session_review: null,
    prediction_snapshot: null,
    prediction_snapshots: [],
  }, overrides || {});
}

function completedProfile() {
  return {
    name: 'Test User',
    sex: 'other',
    age_years: 30,
    height_cm: 175,
    weight_kg: 70,
    body_fat_percent: 20,
    drinks_per_week: 4,
  };
}

function usableReview(beta) {
  return {
    implied_beta_result: {
      usable_for_personalization: true,
      implied_beta: beta || 0.014,
      message: 'High-confidence feedback produced a limited beta calibration signal.',
    },
  };
}

function unusableReview() {
  return {
    implied_beta_result: {
      usable_for_personalization: false,
      implied_beta: null,
      message: 'Calibration signal unavailable because drink timing confidence was not high.',
      rejection_reasons: ['drink_timing_confidence_not_high'],
    },
  };
}

{
  const { S } = loadStorage();
  const state = S.getPredictionPersonalizationState({});
  assert.strictEqual(state.personalization_active, false);
  assert.strictEqual(state.calibration_status, 'no_prediction_metadata');
}

{
  const { S } = loadStorage();
  const state = S.getPredictionPersonalizationState({
    personalization_summary: {
      active: false,
      disabled_by_user: true,
      source_count: 2,
      usable_source_count: 2,
      message: 'Limited personalization is turned off. Using baseline elimination estimate.',
    },
  });
  assert.strictEqual(state.personalization_active, false);
  assert.strictEqual(state.disabled_by_user, true);
  assert.strictEqual(state.calibration_status, 'disabled_by_user');
  assert.strictEqual(state.usable_source_count, 2);
}

{
  const { S } = loadStorage();
  const settings = S.getPersonalizationSettings();
  assert.strictEqual(settings.limited_personalization_enabled, true);
  assert.strictEqual(settings.save_feedback_enabled, true);
  assert.strictEqual(S.isLimitedPersonalizationEnabled(), true);
}

{
  const { S, store } = loadStorage();
  store[S.PERSONALIZATION_SETTINGS_KEY] = '{bad json';
  const settings = S.getPersonalizationSettings();
  assert.strictEqual(settings.limited_personalization_enabled, true);
  assert.strictEqual(settings.save_feedback_enabled, true);
}

{
  const { S } = loadStorage();
  const saved = S.savePersonalizationSettings({
    limited_personalization_enabled: false,
    save_feedback_enabled: true,
  });
  assert.strictEqual(saved.limited_personalization_enabled, false);
  assert.strictEqual(S.getPersonalizationSettings().limited_personalization_enabled, false);
  assert.strictEqual(S.isLimitedPersonalizationEnabled(), false);
}

{
  const { S, store } = loadStorage();
  const session = completedSession({ post_session_review: usableReview(0.014) });
  store[S.STORAGE_KEY] = JSON.stringify([session]);
  S.savePersonalizationSettings({ limited_personalization_enabled: false });
  assert.strictEqual(S.getSessions().length, 1);
  assert.strictEqual(S.getAllImpliedBetas().length, 1);
}

{
  const { S } = loadStorage();
  const session = completedSession({
    post_session_review: {
      implied_beta_result: {
        usable_for_personalization: false,
        implied_beta: null,
        message: 'Calibration signal unavailable because drink log confidence was not high.',
        rejection_reasons: ['drink_log_confidence_not_high'],
      },
    },
  });
  const state = S.getSessionCalibrationState(session);
  assert.strictEqual(state.has_feedback, true);
  assert.strictEqual(state.has_usable_calibration, false);
  assert.strictEqual(state.calibration_status, 'calibration_unavailable');
  assert.deepStrictEqual(state.rejection_reasons, ['drink_log_confidence_not_high']);
}

{
  const { S } = loadStorage();
  const session = completedSession({
    post_session_review: {
      implied_beta_result: {
        usable_for_personalization: true,
        implied_beta: 0.014,
        message: 'High-confidence feedback produced a limited beta calibration signal.',
      },
    },
  });
  const state = S.getSessionCalibrationState(session);
  assert.strictEqual(state.has_usable_calibration, true);
  assert.strictEqual(state.calibration_status, 'usable_calibration');
}

{
  const { S, store } = loadStorage();
  const session = completedSession({
    post_session_review: {
      implied_beta: 0.014,
      vomited: false,
      blackout: false,
    },
  });
  store[S.STORAGE_KEY] = JSON.stringify([session]);
  assert.strictEqual(S.getAllImpliedBetas().length, 0);
  const state = S.getSessionCalibrationState(session);
  assert.strictEqual(state.calibration_status, 'no_calibration_signal_recorded');
}

{
  const { S } = loadStorage();
  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.has_profile, false);
  assert.strictEqual(summary.profile_completed, false);
  assert.strictEqual(summary.total_sessions, 0);
  assert.strictEqual(summary.completed_sessions, 0);
  assert.strictEqual(summary.sessions_with_feedback, 0);
  assert.strictEqual(summary.sessions_with_usable_calibration, 0);
  assert.strictEqual(summary.data_quality_level, 'none');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.has_profile, true);
  assert.strictEqual(summary.profile_completed, true);
  assert.strictEqual(summary.total_sessions, 0);
  assert.strictEqual(summary.data_quality_level, 'stronger_signal_possible');
  assert.strictEqual(summary.baseline_fields_present.weight, true);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession()]);
  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.completed_sessions, 1);
  assert.strictEqual(summary.sessions_with_feedback, 0);
  assert.strictEqual(summary.sessions_with_usable_calibration, 0);
  assert.strictEqual(summary.sessions_with_unusable_calibration, 0);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: {
      implied_beta_result: {
        usable_for_personalization: false,
        implied_beta: null,
        message: 'Calibration signal unavailable because drink timing confidence was not high.',
        rejection_reasons: ['drink_timing_confidence_not_high'],
      },
    },
  })]);
  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.sessions_with_feedback, 1);
  assert.strictEqual(summary.sessions_with_usable_calibration, 0);
  assert.strictEqual(summary.sessions_with_unusable_calibration, 1);
  assert.strictEqual(summary.latest_rejection_reasons.length, 1);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: {
      implied_beta_result: {
        usable_for_personalization: true,
        implied_beta: 0.014,
        message: 'High-confidence feedback produced a limited beta calibration signal.',
      },
    },
  })]);
  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.sessions_with_feedback, 1);
  assert.strictEqual(summary.sessions_with_usable_calibration, 1);
  assert.strictEqual(summary.sessions_with_unusable_calibration, 0);
  assert.strictEqual(summary.data_quality_level, 'limited');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: {
      implied_beta: 0.014,
      vomited: false,
      blackout: false,
    },
  })]);
  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.sessions_with_feedback, 1);
  assert.strictEqual(summary.sessions_with_usable_calibration, 0);
  assert.strictEqual(summary.sessions_with_unusable_calibration, 0);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    prediction_snapshot: {
      created_at: '2026-04-28T01:00:00.000Z',
      personalization_summary: {
        calibration_type: 'limited_beta_only',
        active: true,
        source_count: 2,
        usable_source_count: 1,
        base_beta: 0.015,
        effective_beta: 0.014,
        message: 'Using limited beta calibration from high-confidence feedback.',
      },
    },
  })]);
  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.latest_personalization_active, true);
  assert.strictEqual(summary.usable_source_count, 1);
  assert.strictEqual(summary.latest_base_beta, 0.015);
  assert.strictEqual(summary.latest_effective_beta, 0.014);
}

{
  const { S } = loadStorage();
  const action = S.getPersonalizationNextBestAction(S.getPersonalizationProfileSummary());
  assert.strictEqual(action.action, 'complete_profile');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  const action = S.getPersonalizationNextBestAction(S.getPersonalizationProfileSummary());
  assert.strictEqual(action.action, 'log_completed_session');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession()]);
  const action = S.getPersonalizationNextBestAction(S.getPersonalizationProfileSummary());
  assert.strictEqual(action.action, 'add_feedback');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({ post_session_review: unusableReview() })]);
  const action = S.getPersonalizationNextBestAction(S.getPersonalizationProfileSummary());
  assert.strictEqual(action.action, 'improve_feedback_quality');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({ post_session_review: usableReview(0.014) })]);
  const action = S.getPersonalizationNextBestAction(S.getPersonalizationProfileSummary());
  assert.strictEqual(action.action, 'continue_high_confidence_feedback');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([
    completedSession({
      session_id: 'session-1',
      post_session_review: usableReview(0.014),
      prediction_snapshot: {
        created_at: '2026-04-28T01:00:00.000Z',
        personalization_summary: {
          calibration_type: 'limited_beta_only',
          active: true,
          source_count: 2,
          usable_source_count: 2,
          base_beta: 0.015,
          effective_beta: 0.014,
          message: 'Using limited beta calibration from high-confidence feedback.',
        },
      },
    }),
    completedSession({ session_id: 'session-2', post_session_review: usableReview(0.013) }),
  ]);
  const action = S.getPersonalizationNextBestAction(S.getPersonalizationProfileSummary());
  assert.strictEqual(action.action, 'limited_personalization_active');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: {
      implied_beta: 0.014,
      vomited: false,
      blackout: false,
    },
  })]);
  const summary = S.getPersonalizationProfileSummary();
  const action = S.getPersonalizationNextBestAction(summary);
  assert.strictEqual(summary.sessions_with_usable_calibration, 0);
  assert.strictEqual(action.action, 'improve_feedback_quality');
}

{
  const { S } = loadStorage();
  assert.strictEqual(S.getPersonalizationEvidenceRows().length, 0);
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession()]);
  assert.strictEqual(S.getPersonalizationEvidenceRows().length, 0);
  const withNoFeedback = S.getPersonalizationEvidenceRows({ include_no_feedback: true });
  assert.strictEqual(withNoFeedback.length, 1);
  assert.strictEqual(withNoFeedback[0].has_feedback, false);
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: {
      submitted_at: '2026-04-28T02:00:00.000Z',
      implied_beta: null,
      drink_log_confidence: 'high',
      drink_timing_confidence: 'high',
      missed_drinks: 'no',
    },
  })]);
  const rows = S.getPersonalizationEvidenceRows();
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].calibration_status, 'no_calibration_signal_recorded');
  assert.strictEqual(rows[0].usable_for_calibration, false);
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: Object.assign(unusableReview(), {
      drink_log_confidence: 'low',
      drink_timing_confidence: 'high',
      missed_drinks: 'no',
    }),
  })]);
  const rows = S.getPersonalizationEvidenceRows();
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].calibration_status, 'calibration_unavailable');
  assert.strictEqual(rows[0].usable_for_calibration, false);
  assert.strictEqual(rows[0].rejection_reasons.join(','), 'drink_timing_confidence_not_high');
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: Object.assign(usableReview(0.014), {
      drink_log_confidence: 'high',
      drink_timing_confidence: 'high',
      missed_drinks: 'no',
    }),
  })]);
  const rows = S.getPersonalizationEvidenceRows();
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].usable_for_calibration, true);
  assert.strictEqual(rows[0].implied_beta, 0.014);
  assert.strictEqual(rows[0].beta_source_label, 'Explicit usable limited beta metadata');
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: {
      implied_beta: 0.014,
      drink_log_confidence: 'high',
      drink_timing_confidence: 'high',
      missed_drinks: 'no',
    },
  })]);
  const rows = S.getPersonalizationEvidenceRows();
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].usable_for_calibration, false);
  assert.strictEqual(rows[0].implied_beta, null);
  assert.strictEqual(rows[0].calibration_status, 'no_calibration_signal_recorded');
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([
    completedSession({
      session_id: 'older',
      started_at: '2026-04-27T00:00:00.000Z',
      ended_at: '2026-04-27T03:00:00.000Z',
      post_session_review: usableReview(0.014),
    }),
    completedSession({
      session_id: 'newer',
      started_at: '2026-04-28T00:00:00.000Z',
      ended_at: '2026-04-28T03:00:00.000Z',
      post_session_review: unusableReview(),
    }),
  ]);
  const rows = S.getPersonalizationEvidenceRows();
  assert.strictEqual(rows.length, 2);
  assert.strictEqual(rows[0].session_id, 'newer');
  assert.strictEqual(rows[1].session_id, 'older');
}

{
  const { S } = loadStorage();
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.reliability_level, 'none');
  assert.strictEqual(reliability.usable_signal_count, 0);
  assert.strictEqual(reliability.total_feedback_count, 0);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.reliability_level, 'baseline_only');
  assert.strictEqual(reliability.reliability_label, 'Baseline estimate only');
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: { notes: 'subjective context only' },
  })]);
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.reliability_level, 'feedback_saved_no_calibration');
  assert.strictEqual(reliability.no_signal_feedback_count, 1);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({ post_session_review: unusableReview() })]);
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.reliability_level, 'feedback_saved_no_calibration');
  assert.strictEqual(reliability.unusable_signal_count, 1);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({ post_session_review: usableReview(0.014) })]);
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.reliability_level, 'limited_single_signal');
  assert.strictEqual(reliability.usable_signal_count, 1);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([
    completedSession({ session_id: 'usable-1', post_session_review: usableReview(0.014) }),
    completedSession({ session_id: 'usable-2', post_session_review: usableReview(0.013) }),
  ]);
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.reliability_level, 'limited_multi_signal');
  assert.strictEqual(reliability.usable_signal_count, 2);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([
    completedSession({ session_id: 'usable-1', post_session_review: usableReview(0.014) }),
    completedSession({ session_id: 'usable-2', post_session_review: usableReview(0.013) }),
    completedSession({ session_id: 'unusable-1', post_session_review: unusableReview() }),
    completedSession({ session_id: 'unusable-2', post_session_review: unusableReview() }),
    completedSession({ session_id: 'unusable-3', post_session_review: unusableReview() }),
  ]);
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.reliability_level, 'limited_but_mixed_quality');
  assert.strictEqual(reliability.usable_signal_count, 2);
  assert.strictEqual(reliability.unusable_signal_count, 3);
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: {
      implied_beta: 0.014,
      drink_log_confidence: 'high',
      drink_timing_confidence: 'high',
      missed_drinks: 'no',
    },
  })]);
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.reliability_level, 'feedback_saved_no_calibration');
  assert.strictEqual(reliability.usable_signal_count, 0);
  assert.strictEqual(reliability.no_signal_feedback_count, 1);
}

// ── E2E simulation (localStorage + helpers; no HTTP) ─────────────────────
function predictionSnapActive(active, disabledUser) {
  return {
    created_at: '2026-04-29T01:00:00.000Z',
    personalization_summary: {
      calibration_type: 'limited_beta_only',
      active,
      disabled_by_user: !!disabledUser,
      source_count: 1,
      usable_source_count: 1,
      base_beta: 0.015,
      effective_beta: disabledUser ? 0.015 : 0.013,
      message: disabledUser
        ? 'Limited personalization is turned off. Using baseline elimination estimate.'
        : 'Using limited beta calibration from high-confidence feedback.',
    },
  };
}

{
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  const sess1 = completedSession({
    session_id: 'e2e-sess-a',
    post_session_review: usableReview(0.014),
    prediction_snapshots: [predictionSnapActive(true, false)],
  });
  const sess2 = completedSession({
    session_id: 'e2e-sess-b',
    started_at: '2026-04-29T02:00:00.000Z',
    updated_at: '2026-04-29T02:00:00.000Z',
    post_session_review: usableReview(0.013),
    prediction_snapshots: [predictionSnapActive(true, false)],
  });
  store[S.STORAGE_KEY] = JSON.stringify([sess1, sess2]);

  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.completed_sessions, 2);
  assert.strictEqual(summary.sessions_with_feedback, 2);
  assert.strictEqual(summary.sessions_with_usable_calibration, 2);
  assert.strictEqual(summary.latest_personalization_active, true);

  const evidence = S.getPersonalizationEvidenceRows();
  assert.strictEqual(evidence.filter((row) => row.usable_for_calibration).length, 2);
  assert.strictEqual(evidence.length, 2);

  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.usable_signal_count, 2);
  assert.strictEqual(reliability.reliability_level, 'limited_multi_signal');

  const action = S.getPersonalizationNextBestAction(summary);
  assert.strictEqual(action.action, 'limited_personalization_active');

  assert.strictEqual(S.getAllImpliedBetas().length, 2);
  assert.strictEqual(S.isLimitedPersonalizationEnabled(), true);

  S.savePersonalizationSettings({ limited_personalization_enabled: false });
  assert.strictEqual(S.isLimitedPersonalizationEnabled(), false);
  assert.strictEqual(S.getAllImpliedBetas().length, 2, 'feedback evidence must remain after toggle off');
}

{
  /** Simulated full page reload: new VM context reads only persisted personalization key */
  const { S, store } = loadStorage();
  S.savePersonalizationSettings({ limited_personalization_enabled: false });
  const persisted = store[S.PERSONALIZATION_SETTINGS_KEY];
  const settingsKey = S.PERSONALIZATION_SETTINGS_KEY;
  assert.ok(persisted.includes('false'));

  const freshSandbox = {
    console,
    crypto: { randomUUID: () => 'reload-ctx-' + Math.random().toString(36).slice(2) },
    localStorage: {
      getItem(key) {
        return key === settingsKey ? persisted : null;
      },
      setItem() {
        throw new Error('reload simulation is read-only');
      },
      removeItem() {},
    },
  };
  freshSandbox.window = freshSandbox;
  vm.runInNewContext(fs.readFileSync('frontend/session-storage.js', 'utf8'), freshSandbox);

  assert.strictEqual(
    freshSandbox.SaferSessionStorage.getPersonalizationSettings().limited_personalization_enabled,
    false,
  );
  assert.strictEqual(freshSandbox.SaferSessionStorage.isLimitedPersonalizationEnabled(), false);
}

{
  /** disabled_by_user + saved snapshot mirrors calculator after POST /predict when toggle off */
  const { S, store } = loadStorage();
  store[S.PROFILE_KEY] = JSON.stringify(completedProfile());
  const sess = completedSession({
    session_id: 'e2e-off',
    post_session_review: usableReview(0.014),
    prediction_snapshots: [predictionSnapActive(false, true)],
  });
  store[S.STORAGE_KEY] = JSON.stringify([sess]);

  const state = S.getPredictionPersonalizationState(
    sess.prediction_snapshots[sess.prediction_snapshots.length - 1],
  );
  assert.strictEqual(state.disabled_by_user, true);
  assert.strictEqual(state.personalization_active, false);

  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.latest_personalization_active, false);
}

// ── Personalization reset / delete controls v1 ───────────────────────────
{
  const { S, store } = loadStorage();
  S.savePersonalizationSettings({ limited_personalization_enabled: false });
  S.clearPersonalizationSettings();
  assert.strictEqual(store[S.PERSONALIZATION_SETTINGS_KEY], undefined);
  assert.strictEqual(S.getPersonalizationSettings().limited_personalization_enabled, true);
  assert.strictEqual(S.isLimitedPersonalizationEnabled(), true);
}

{
  const { S, store } = loadStorage();
  store[S.PERSONALIZATION_SETTINGS_KEY] = '{not-json';
  assert.strictEqual(S.getPersonalizationSettings().limited_personalization_enabled, true);
  S.resetPersonalizationSettingsToDefault();
  assert.ok(store[S.PERSONALIZATION_SETTINGS_KEY].includes('limited_personalization_enabled'));
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = 'not-valid-json';
  assert.doesNotThrow(() => S.clearCalibrationEvidence());
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    session_id: 'persist-notes',
    post_session_review: Object.assign({ notes: 'keep subjective text' }, usableReview(0.014)),
  })]);
  assert.strictEqual(S.getAllImpliedBetas().length, 1);
  S.clearCalibrationEvidence();
  const s = S.getSessions()[0];
  assert.strictEqual(S.getAllImpliedBetas().length, 0);
  assert.strictEqual(s.post_session_review.notes, 'keep subjective text');
  const state = S.getSessionCalibrationState(s);
  assert.strictEqual(state.calibration_status, 'no_calibration_signal_recorded');
  const summary = S.getPersonalizationProfileSummary();
  assert.strictEqual(summary.sessions_with_usable_calibration, 0);
  const reliability = S.getPersonalizationReliabilitySummary();
  assert.strictEqual(reliability.usable_signal_count, 0);
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    session_id: 'snap-clear',
    post_session_review: usableReview(0.014),
    prediction_snapshots: [{
      created_at: '2026-05-01T00:00:00.000Z',
      personalization_summary: {
        calibration_type: 'limited_beta_only',
        active: true,
        source_count: 1,
        usable_source_count: 1,
        base_beta: 0.015,
        effective_beta: 0.012,
      },
      response_payload: { personalization: { active: true } },
    }],
  })]);
  S.clearPersonalizationPredictionSnapshots();
  const snap = S.latestPredictionSnapshot(S.getSessions()[0]);
  assert.strictEqual(snap.personalization_summary, undefined);
  assert.strictEqual(snap.response_payload.personalization, undefined);
  assert.strictEqual(S.getPersonalizationProfileSummary().latest_personalization_active, false);
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: Object.assign({}, usableReview(0.014), { notes: 'n' }),
  })]);
  S.savePersonalizationSettings({ limited_personalization_enabled: false });
  S.clearAllPersonalizationData();
  assert.strictEqual(S.isLimitedPersonalizationEnabled(), true);
  assert.strictEqual(S.getAllImpliedBetas().length, 0);
}

{
  const { S, store } = loadStorage();
  store[S.STORAGE_KEY] = JSON.stringify([completedSession({
    post_session_review: {
      notes: 'legacy only',
      implied_beta: 0.016,
      drink_log_confidence: 'high',
    },
  })]);
  assert.strictEqual(S.getAllImpliedBetas().length, 0);
  S.clearCalibrationEvidence();
  assert.strictEqual(S.getSessions()[0].post_session_review.notes, 'legacy only');
  assert.strictEqual(S.getSessions()[0].post_session_review.implied_beta, null);
  assert.strictEqual(S.getAllImpliedBetas().length, 0);
}

console.log('session-storage helper tests passed');
