/**
 * SaferSessionStorage — session list + profile persistence.
 * Keys: safer_sessions, safer_active_session_id, safer_user_profile
 */
(function (global) {
  var STORAGE_KEY = 'safer_sessions';
  var ACTIVE_KEY  = 'safer_active_session_id';
  var PROFILE_KEY = 'safer_user_profile';
  var PERSONALIZATION_SETTINGS_KEY = 'safer_personalization_settings';

  /* ── ID generators ── */
  function genId(prefix) {
    if (global.crypto && typeof global.crypto.randomUUID === 'function') return global.crypto.randomUUID();
    return (prefix || 'id') + '_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
  }

  /* ── Default shapes ── */
  function defaultSessionShape() {
    var now = new Date().toISOString();
    return {
      schema_version: 2,
      session_id: genId('sess'),
      title: 'Drinking session — ' + new Date().toLocaleString(),
      user_id: null,
      status: 'draft',
      started_at: now,
      updated_at: now,
      ended_at: null,
      events: [],
      review_status: 'pending',
      post_session_review: null,
      prediction_snapshot: null,
      prediction_snapshots: [],
      profile_snapshot: null,
      inputs: { drinks: 0, drink_type: 'standard', hours_elapsed: 0, food_intake: 'unknown', hydration: 'unknown', sleep: 'unknown', fasting: 'unknown' },
      feedback: { perceived_intoxication: null, hangover_severity: null, blackout: null, vomiting: null }
    };
  }

  function finiteNumber(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function defaultPersonalizationSettings() {
    return {
      schema_version: 1,
      limited_personalization_enabled: true,
      save_feedback_enabled: true,
      updated_at: new Date().toISOString()
    };
  }

  function normalizePersonalizationSettings(raw) {
    raw = raw && typeof raw === 'object' ? raw : {};
    var defaults = defaultPersonalizationSettings();
    return {
      schema_version: 1,
      limited_personalization_enabled: raw.limited_personalization_enabled !== false,
      save_feedback_enabled: raw.save_feedback_enabled !== false,
      updated_at: typeof raw.updated_at === 'string' && raw.updated_at ? raw.updated_at : defaults.updated_at
    };
  }

  function hoursFromStart(session, timestamp) {
    var start = new Date(session.started_at || Date.now()).getTime();
    var eventTime = new Date(timestamp || Date.now()).getTime();
    if (!Number.isFinite(start) || !Number.isFinite(eventTime)) return 0;
    return Math.max(0, (eventTime - start) / 3600000);
  }

  function normalizeDrinkEvent(session, e) {
    if (!e || e.event_type !== 'drink') return e;
    var timestamp = e.timestamp || new Date().toISOString();
    if (!e.timestamp) e.timestamp = timestamp;
    if (finiteNumber(e.hours_from_session_start) == null) {
      e.hours_from_session_start = Number(hoursFromStart(session, timestamp).toFixed(4));
    }
    if (finiteNumber(e.grams_alcohol) == null && finiteNumber(e.standard_drinks) != null) {
      e.grams_alcohol = finiteNumber(e.standard_drinks) * 14;
    }
    if (finiteNumber(e.standard_drinks) == null && finiteNumber(e.grams_alcohol) != null) {
      e.standard_drinks = finiteNumber(e.grams_alcohol) / 14;
    }
    if (!e.label) e.label = (finiteNumber(e.standard_drinks) || 0).toFixed(2) + ' standard drinks';
    return e;
  }

  function ensureSessionShape(s) {
    if (!s || typeof s !== 'object') return defaultSessionShape();
    if (!Array.isArray(s.events)) s.events = [];
    s.events = s.events.map(function(e) { return normalizeDrinkEvent(s, e); });
    if (!s.title) s.title = 'Drinking session — ' + new Date(s.started_at || Date.now()).toLocaleString();
    if (!s.review_status) s.review_status = 'pending';
    if (s.post_session_review && typeof s.post_session_review !== 'object') s.post_session_review = null;
    if (s.post_session_review) s.review_status = 'completed';
    else if (s.status === 'completed') s.review_status = 'pending';
    if (!s.inputs || typeof s.inputs !== 'object') s.inputs = defaultSessionShape().inputs;
    if (!s.feedback || typeof s.feedback !== 'object') s.feedback = defaultSessionShape().feedback;
    if (!Array.isArray(s.prediction_snapshots)) s.prediction_snapshots = [];
    if (s.prediction_snapshot && s.prediction_snapshots.length === 0) {
      s.prediction_snapshots.push(s.prediction_snapshot);
    }
    if (s.profile_snapshot && typeof s.profile_snapshot !== 'object') s.profile_snapshot = null;
    if (s.profile_snapshot == null) s.profile_snapshot = null;
    s.schema_version = Math.max(Number(s.schema_version) || 1, 2);
    return s;
  }

  /* ── Storage helpers ── */
  function getSessions() {
    try {
      var raw = global.localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.map(ensureSessionShape) : [];
    } catch (e) { return []; }
  }

  function saveSessions(sessions) {
    global.localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  }

  function getPersonalizationSettings() {
    try {
      var raw = global.localStorage.getItem(PERSONALIZATION_SETTINGS_KEY);
      if (!raw) return defaultPersonalizationSettings();
      return normalizePersonalizationSettings(JSON.parse(raw));
    } catch(e) {
      return defaultPersonalizationSettings();
    }
  }

  function savePersonalizationSettings(settings) {
    var current = getPersonalizationSettings();
    var next = normalizePersonalizationSettings(Object.assign({}, current, settings || {}, {
      updated_at: new Date().toISOString()
    }));
    global.localStorage.setItem(PERSONALIZATION_SETTINGS_KEY, JSON.stringify(next));
    return next;
  }

  function isLimitedPersonalizationEnabled() {
    return getPersonalizationSettings().limited_personalization_enabled === true;
  }

  /** Remove settings key; next read uses same defaults as a fresh install. */
  function clearPersonalizationSettings() {
    try {
      global.localStorage.removeItem(PERSONALIZATION_SETTINGS_KEY);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: String(e && e.message ? e.message : e) };
    }
  }

  /** Write explicit default settings object (same values as missing key). */
  function resetPersonalizationSettingsToDefault() {
    var d = defaultPersonalizationSettings();
    try {
      global.localStorage.setItem(PERSONALIZATION_SETTINGS_KEY, JSON.stringify(d));
      return { ok: true, settings: d };
    } catch (e) {
      return { ok: false, error: String(e && e.message ? e.message : e) };
    }
  }

  function stripPersonalizationFromSnapshot(snap) {
    if (!snap || typeof snap !== 'object') return snap;
    var out = Object.assign({}, snap);
    delete out.personalization_summary;
    if (out.response_payload && typeof out.response_payload === 'object') {
      var rp = Object.assign({}, out.response_payload);
      delete rp.personalization;
      out.response_payload = rp;
    }
    return out;
  }

  /**
   * Strip personalization_summary from stored prediction snapshots.
   * Preserves estimate/BAC/curve fields; does not delete sessions or feedback.
   */
  function clearPersonalizationPredictionSnapshots() {
    var all = getSessions();
    var touched = 0;
    all.forEach(function(s) {
      var changed = false;
      if (s.prediction_snapshot) {
        s.prediction_snapshot = stripPersonalizationFromSnapshot(s.prediction_snapshot);
        changed = true;
      }
      if (Array.isArray(s.prediction_snapshots) && s.prediction_snapshots.length) {
        s.prediction_snapshots = s.prediction_snapshots.map(function(sn) {
          return stripPersonalizationFromSnapshot(sn);
        });
        changed = true;
      }
      if (changed) {
        s.updated_at = new Date().toISOString();
        touched += 1;
      }
    });
    if (touched) saveSessions(all);
    return { sessions_updated: touched, ok: true };
  }

  /**
   * Remove implied_beta_result and legacy implied_beta from saved feedback.
   * Subjective fields (notes, confidence, symptoms) stay; sessions stay.
   */
  function clearCalibrationEvidence() {
    var all = getSessions();
    var touched = 0;
    all.forEach(function(s) {
      var review = s.post_session_review;
      if (!review || typeof review !== 'object') return;
      var hadCalib = review.implied_beta_result != null || finiteNumber(review.implied_beta) != null;
      if (!hadCalib) return;
      var raw = Object.assign({}, review);
      delete raw.implied_beta_result;
      delete raw.implied_beta;
      s.post_session_review = normalizePostSessionReview(raw);
      s.updated_at = new Date().toISOString();
      touched += 1;
    });
    if (touched) saveSessions(all);
    return { sessions_with_feedback_cleared: touched, ok: true };
  }

  /**
   * Settings → defaults, strip snapshot personalization, clear calibration metadata from feedback.
   * Does not delete sessions, events, or subjective feedback text. Does not remove profile.
   */
  function clearAllPersonalizationData() {
    var snapRes = clearPersonalizationPredictionSnapshots();
    var calRes = clearCalibrationEvidence();
    var setRes = resetPersonalizationSettingsToDefault();
    return {
      ok: !!(setRes && setRes.ok),
      prediction_snapshots: snapRes,
      calibration: calRes,
      settings: setRes
    };
  }

  function getSessionById(id) {
    if (!id) return null;
    return getSessions().find(function(s) { return s.session_id === id; }) || null;
  }

  function updateSession(updated) {
    ensureSessionShape(updated);
    var all = getSessions();
    var idx = all.findIndex(function(s) { return s.session_id === updated.session_id; });
    if (idx === -1) return false;
    all[idx] = updated;
    saveSessions(all);
    return true;
  }

  function createSession(partial) {
    var base = defaultSessionShape();
    if (partial && typeof partial === 'object') {
      if (partial.title) base.title = String(partial.title);
      if (Array.isArray(partial.events)) base.events = partial.events.slice();
    }
    base.updated_at = base.started_at;
    var all = getSessions();
    all.push(base);
    saveSessions(all);
    try { global.localStorage.setItem(ACTIVE_KEY, base.session_id); } catch(e) {}
    return base;
  }

  function deleteSession(id) {
    if (!id) return { deleted: false };
    var all = getSessions();
    var kept = [], deleted = null;
    all.forEach(function(s) { if (s.session_id === id) deleted = s; else kept.push(s); });
    if (!deleted) return { deleted: false };
    var wasActive = false;
    try { wasActive = global.localStorage.getItem(ACTIVE_KEY) === id; } catch(e) {}
    saveSessions(kept);
    if (wasActive) { try { global.localStorage.removeItem(ACTIVE_KEY); } catch(e) {} }
    return { deleted: true, session_id: id, was_active: wasActive };
  }

  function getActiveDraftSession() {
    try {
      var id = global.localStorage.getItem(ACTIVE_KEY);
      if (!id) return null;
      var s = getSessionById(id);
      if (s && s.status === 'draft') return s;
      global.localStorage.removeItem(ACTIVE_KEY);
      return null;
    } catch(e) { return null; }
  }

  function setActiveDraftSessionId(id) {
    if (id) global.localStorage.setItem(ACTIVE_KEY, id);
    else { try { global.localStorage.removeItem(ACTIVE_KEY); } catch(e) {} }
  }

  function clearActiveDraftSessionId() {
    try { global.localStorage.removeItem(ACTIVE_KEY); } catch(e) {}
  }

  function getOrCreateActiveDraftSession(partial) {
    return getActiveDraftSession() || createSession(partial || {});
  }

  function addEventToSession(sessionId, event) {
    if (!sessionId) return null;
    var session = getSessionById(sessionId);
    if (!session) return null;
    ensureSessionShape(session);
    var now = new Date().toISOString();
    var nextEvent = Object.assign({ event_id: genId('evt'), event_type: 'other', timestamp: now }, event || {});
    if (nextEvent.event_type === 'drink' && finiteNumber(nextEvent.hours_from_session_start) == null) {
      nextEvent.hours_from_session_start = Number(hoursFromStart(session, nextEvent.timestamp).toFixed(4));
    }
    session.events.push(normalizeDrinkEvent(session, nextEvent));
    session.updated_at = now;
    updateSession(session);
    return session;
  }

  function completeSession(sessionId) {
    if (!sessionId) return null;
    var session = getSessionById(sessionId);
    if (!session) return null;
    ensureSessionShape(session);
    var now = new Date().toISOString();
    session.status = 'completed';
    session.review_status = session.post_session_review ? 'completed' : 'pending';
    session.ended_at = now;
    session.updated_at = now;
    updateSession(session);
    clearActiveDraftSessionId();
    return session;
  }

  function isReviewPending(s) {
    s = ensureSessionShape(s);
    return s.status === 'completed' && s.review_status !== 'completed' && !s.post_session_review;
  }

  function getSessionsPendingReview() {
    return getSessions().filter(isReviewPending);
  }

  /* ── Normalize post-session review ── */
  function clampInt(v, lo, hi, fallback) {
    var n = parseInt(v, 10);
    return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : fallback;
  }
  function optNum(v) {
    if (v === '' || v == null) return null;
    var n = Number(v);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }
  function normHydration(v) {
    var allowed = { unknown:1, low:1, normal:1, high:1 };
    var s = String(v || 'unknown').toLowerCase();
    return allowed[s] ? s : 'unknown';
  }
  function normFood(v) {
    var allowed = { none:1, low:1, medium:1, mid:1, high:1 };
    var s = String(v || 'none').toLowerCase();
    if (s === 'mid') return 'medium';
    return allowed[s] ? s : 'none';
  }
  function normConfidence(v) {
    var allowed = { low:1, medium:1, high:1, unknown:1 };
    var s = String(v || 'unknown').toLowerCase();
    return allowed[s] ? s : 'unknown';
  }
  function normMissedDrinks(v) {
    var allowed = { no:1, some:1, many:1, unknown:1 };
    var s = String(v || 'unknown').toLowerCase();
    if (s === 'yes' || s === 'unsure') return s === 'yes' ? 'some' : 'unknown';
    return allowed[s] ? s : 'unknown';
  }
  function normalizeImpliedBetaResult(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var beta = finiteNumber(raw.implied_beta);
    return Object.assign({}, raw, {
      implied_beta: beta,
      usable_for_personalization: raw.usable_for_personalization === true,
      confidence: finiteNumber(raw.confidence),
      validity_flags: Array.isArray(raw.validity_flags) ? raw.validity_flags.slice() : [],
      warnings: Array.isArray(raw.warnings) ? raw.warnings.slice() : []
    });
  }

  function normalizePostSessionReview(raw) {
    raw = (raw && typeof raw === 'object') ? raw : {};
    var impliedResult = normalizeImpliedBetaResult(raw.implied_beta_result);
    var legacyBeta = finiteNumber(raw.implied_beta);
    if (legacyBeta == null && impliedResult && impliedResult.implied_beta != null) legacyBeta = impliedResult.implied_beta;
    var submittedAt = raw.submitted_at || raw.reviewed_at || new Date().toISOString();
    return {
      schema_version: Math.max(Number(raw.schema_version) || 1, 1),
      submitted_at: submittedAt,
      reviewed_at: submittedAt,
      hangover_severity: clampInt(raw.hangover_severity, 0, 5, 0),
      perceived_peak_intoxication: clampInt(raw.perceived_peak_intoxication, 0, 5, 0),
      vomited: raw.vomited === true,
      blackout: raw.blackout === true,
      memory_gap: raw.memory_gap === true,
      felt_sober_hours: optNum(raw.felt_sober_hours),   // numeric now
      felt_sober_time: String(raw.felt_sober_time || '').trim(),
      food_intake: normFood(raw.food_intake),
      drink_log_confidence: normConfidence(raw.drink_log_confidence),
      drink_timing_confidence: normConfidence(raw.drink_timing_confidence || raw.timing_confidence),
      missed_drinks: normMissedDrinks(raw.missed_drinks),
      final_bac_anchor: optNum(raw.final_bac_anchor) == null ? 0.02 : optNum(raw.final_bac_anchor),
      sleep_hours_after: optNum(raw.sleep_hours_after),
      hydration_after: normHydration(raw.hydration_after),
      notes: String(raw.notes || '').trim(),
      implied_beta: legacyBeta,
      implied_beta_result: impliedResult
    };
  }

  function savePostSessionReview(sessionId, review) {
    if (!sessionId) return null;
    var session = getSessionById(sessionId);
    if (!session || session.status !== 'completed') return null;
    ensureSessionShape(session);
    session.post_session_review = normalizePostSessionReview(review);
    session.review_status = 'completed';
    session.updated_at = session.post_session_review.submitted_at;
    updateSession(session);
    return session;
  }

  function markReviewCompleted(sessionId) {
    var session = getSessionById(sessionId);
    if (!session) return null;
    session.review_status = 'completed';
    session.updated_at = new Date().toISOString();
    updateSession(session);
    return session;
  }

  /* ── Profile helpers ── */
  function getProfile() {
    try {
      var raw = global.localStorage.getItem(PROFILE_KEY);
      if (!raw) return null;
      var d = JSON.parse(raw);
      return d && typeof d === 'object' ? d : null;
    } catch(e) { return null; }
  }

  function saveProfile(profile) {
    global.localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
  }

  /* ── Implied beta helpers ── */
  function isPlausibleBeta(v) {
    return typeof v === 'number' && Number.isFinite(v) && v >= 0.005 && v <= 0.030;
  }

  // Prediction history is limited to beta/elimination-rate calibration. Only
  // return feedback explicitly marked usable; subjective feedback is not
  // ground-truth BAC, and new prediction-history fields need tests + gates.
  function getAllImpliedBetas() {
    var seen = {};
    return getSessions().reduce(function(acc, s) {
      if (!s || seen[s.session_id]) return acc;
      if (s.status !== 'completed' && s.status !== 'reviewed') return acc;
      var review = s.post_session_review;
      if (!review) return acc;

      var result = review.implied_beta_result;
      if (result && result.usable_for_personalization === true && isPlausibleBeta(result.implied_beta)) {
        acc.push(Object.assign({}, result, {
          source_session_id: s.session_id
        }));
        seen[s.session_id] = true;
        return acc;
      }

      return acc;
    }, []);
  }

  function latestPredictionSnapshot(session) {
    if (session && Array.isArray(session.prediction_snapshots) && session.prediction_snapshots.length) {
      return session.prediction_snapshots[session.prediction_snapshots.length - 1];
    }
    return session && session.prediction_snapshot ? session.prediction_snapshot : null;
  }

  function normalizePredictionPersonalization(raw) {
    raw = (raw && typeof raw === 'object') ? raw : {};
    return {
      calibration_type: raw.calibration_type || 'limited_beta_only',
      personalization_active: raw.active === true,
      source_count: Math.max(0, Number(raw.source_count) || 0),
      usable_source_count: Math.max(0, Number(raw.usable_source_count) || 0),
      base_beta: finiteNumber(raw.base_beta),
      effective_beta: finiteNumber(raw.effective_beta),
      disabled_by_user: raw.disabled_by_user === true,
      calibration_message: raw.message || ''
    };
  }

  function getPredictionPersonalizationState(sessionOrSnapshot) {
    var snap = sessionOrSnapshot && (sessionOrSnapshot.prediction_snapshot || sessionOrSnapshot.prediction_snapshots)
      ? latestPredictionSnapshot(sessionOrSnapshot)
      : sessionOrSnapshot;
    var summary = snap && (snap.personalization_summary ||
      (snap.response_payload && snap.response_payload.personalization));
    var normalized = normalizePredictionPersonalization(summary);
    if (!summary) {
      normalized.calibration_status = 'no_prediction_metadata';
      normalized.calibration_message = 'No personalization metadata recorded for this estimate.';
    } else if (normalized.personalization_active) {
      normalized.calibration_status = 'active';
      normalized.calibration_message = normalized.calibration_message ||
        'Limited personalization active: high-confidence prior feedback is adjusting the elimination estimate.';
    } else if (normalized.disabled_by_user) {
      normalized.calibration_status = 'disabled_by_user';
      normalized.calibration_message = normalized.calibration_message ||
        'Limited personalization is turned off. Using baseline elimination estimate.';
    } else if (normalized.source_count > 0 && normalized.usable_source_count === 0) {
      normalized.calibration_status = 'feedback_not_used';
      normalized.calibration_message = normalized.calibration_message ||
        'Feedback saved, but not used for calibration because usable context was not available.';
    } else {
      normalized.calibration_status = 'inactive';
      normalized.calibration_message = normalized.calibration_message ||
        'Personalization inactive: using baseline elimination estimate.';
    }
    return normalized;
  }

  function getSessionCalibrationState(session) {
    session = ensureSessionShape(session || {});
    var review = session.post_session_review;
    var result = review && review.implied_beta_result;
    var prediction = getPredictionPersonalizationState(session);
    var out = {
      has_feedback: !!review,
      has_usable_calibration: false,
      calibration_status: 'no_feedback',
      calibration_message: 'No feedback saved yet.',
      rejection_reasons: [],
      personalization_active: prediction.personalization_active,
      usable_source_count: prediction.usable_source_count,
      source_count: prediction.source_count
    };

    if (!review) return out;

    out.has_feedback = true;
    if (result && result.usable_for_personalization === true && isPlausibleBeta(result.implied_beta)) {
      out.has_usable_calibration = true;
      out.calibration_status = 'usable_calibration';
      out.calibration_message = result.message ||
        'High-confidence feedback produced a limited beta calibration signal.';
    } else if (result) {
      out.calibration_status = 'calibration_unavailable';
      out.calibration_message = result.message ||
        'Feedback saved. Calibration signal unavailable for this session.';
      out.rejection_reasons = Array.isArray(result.rejection_reasons) ? result.rejection_reasons.slice() : [];
    } else {
      out.calibration_status = 'no_calibration_signal_recorded';
      out.calibration_message = 'Feedback saved. No calibration signal recorded for this session.';
    }
    return out;
  }

  function hasCompletedProfile(profile) {
    if (!profile || typeof profile !== 'object') return false;
    var sexOk = profile.sex === 'male' || profile.sex === 'female' || profile.sex === 'other';
    var ageOk = Boolean(profile.age_band) || finiteNumber(profile.age_years) != null;
    var heightOk = finiteNumber(profile.height_in) != null || finiteNumber(profile.height_cm) != null;
    var weightOk = finiteNumber(profile.weight_lbs) != null || finiteNumber(profile.weight_kg) != null;
    var bodyFatOk = finiteNumber(profile.body_fat_percent) != null;
    return sexOk && ageOk && heightOk && weightOk && bodyFatOk;
  }

  function baselineFieldsPresent(profile) {
    profile = profile && typeof profile === 'object' ? profile : {};
    return {
      sex: profile.sex === 'male' || profile.sex === 'female' || profile.sex === 'other',
      age: Boolean(profile.age_band) || finiteNumber(profile.age_years) != null,
      height: finiteNumber(profile.height_in) != null || finiteNumber(profile.height_cm) != null,
      weight: finiteNumber(profile.weight_lbs) != null || finiteNumber(profile.weight_kg) != null,
      body_fat_percent: finiteNumber(profile.body_fat_percent) != null,
      drinks_per_week: finiteNumber(profile.drinks_per_week) != null
    };
  }

  function getLatestPersonalizationFromSessions(sessions) {
    return sessions.reduce(function(best, session) {
      var snap = latestPredictionSnapshot(session);
      if (!snap) return best;
      var state = getPredictionPersonalizationState(snap);
      var timestamp = new Date(snap.created_at || session.updated_at || session.started_at || 0).getTime();
      if (!best || timestamp >= best.timestamp) {
        return Object.assign({ timestamp: timestamp }, state);
      }
      return best;
    }, null);
  }

  function getPersonalizationProfileSummary() {
    var profile = getProfile();
    var sessions = getSessions();
    var completed = sessions.filter(function(s) { return s && s.status === 'completed'; });
    var feedbackCount = 0;
    var usableCount = 0;
    var unusableCount = 0;
    var latestRejectionReasons = [];

    completed.forEach(function(session) {
      var state = getSessionCalibrationState(session);
      if (!state.has_feedback) return;
      feedbackCount += 1;
      if (state.has_usable_calibration) {
        usableCount += 1;
      } else if (state.calibration_status === 'calibration_unavailable') {
        unusableCount += 1;
        if (state.rejection_reasons.length) latestRejectionReasons = state.rejection_reasons.slice();
      }
    });

    var latest = getLatestPersonalizationFromSessions(sessions);
    var completedProfile = hasCompletedProfile(profile);
    var dataQualityLevel = 'none';
    var dataQualityMessage = 'Complete a baseline profile and save sessions to build a limited personalization profile.';
    if (usableCount > 0 || (latest && latest.personalization_active)) {
      dataQualityLevel = 'limited';
      dataQualityMessage = 'Limited personalization has at least one high-confidence beta calibration signal.';
    } else if (completedProfile && (completed.length > 0 || feedbackCount > 0)) {
      dataQualityLevel = 'stronger_signal_possible';
      dataQualityMessage = 'More high-confidence feedback can strengthen the limited elimination-rate calibration signal.';
    } else if (completedProfile) {
      dataQualityLevel = 'stronger_signal_possible';
      dataQualityMessage = 'Log completed sessions and optional high-confidence feedback to build a calibration signal.';
    }

    return {
      profile_completed: completedProfile,
      profile_source: profile ? 'local_storage' : 'none',
      has_profile: !!profile,
      baseline_fields_present: baselineFieldsPresent(profile),
      total_sessions: sessions.length,
      completed_sessions: completed.length,
      sessions_with_feedback: feedbackCount,
      sessions_with_usable_calibration: usableCount,
      sessions_with_unusable_calibration: unusableCount,
      usable_source_count: latest ? latest.usable_source_count : usableCount,
      latest_personalization_active: latest ? latest.personalization_active : false,
      latest_effective_beta: latest ? latest.effective_beta : null,
      latest_base_beta: latest ? latest.base_beta : null,
      latest_calibration_message: latest
        ? latest.calibration_message
        : 'No prediction personalization metadata recorded yet.',
      latest_rejection_reasons: latestRejectionReasons,
      data_quality_level: dataQualityLevel,
      data_quality_message: dataQualityMessage
    };
  }

  function getPersonalizationNextBestAction(summary) {
    summary = summary || getPersonalizationProfileSummary();
    var base = {
      action: 'no_action_available',
      title: 'No personalization action available',
      message: 'No next step is available right now.',
      supporting_reasons: [],
      recommended_steps: [],
      priority: 'low'
    };

    if (!summary.profile_completed) {
      return Object.assign({}, base, {
        action: 'complete_profile',
        title: 'Complete your baseline profile',
        message: 'A completed profile is needed before limited personalization can use session feedback.',
        supporting_reasons: ['Baseline profile is incomplete or missing.'],
        recommended_steps: [
          'Open My Profile.',
          'Save body size, body-fat estimate, and weekly drinking context.',
          'Return to the calculator to log sessions.'
        ],
        href: 'input.html',
        cta_label: 'Complete profile',
        priority: 'high'
      });
    }

    if (summary.completed_sessions === 0) {
      return Object.assign({}, base, {
        action: 'log_completed_session',
        title: 'Log a completed session',
        message: 'Completed sessions create the session history needed for future estimate adjustment.',
        supporting_reasons: ['No completed sessions are saved yet.'],
        recommended_steps: [
          'Start a session on the BAC Calculator.',
          'Log drinks as close to their actual timing as possible.',
          'End the session when you are done logging.'
        ],
        href: 'bac-calculator.html',
        cta_label: 'Start session',
        priority: 'high'
      });
    }

    if (summary.sessions_with_feedback === 0) {
      return Object.assign({}, base, {
        action: 'add_feedback',
        title: 'Add optional feedback after a completed session',
        message: 'Feedback is saved as subjective context. High-confidence feedback may create a limited calibration signal.',
        supporting_reasons: ['Completed sessions exist, but no feedback is saved yet.'],
        recommended_steps: [
          'Open History.',
          'Choose a completed session.',
          'Add optional feedback if you remember the session context clearly.'
        ],
        href: 'history.html',
        cta_label: 'View history',
        priority: 'medium'
      });
    }

    if (summary.sessions_with_usable_calibration === 0) {
      return Object.assign({}, base, {
        action: 'improve_feedback_quality',
        title: 'Improve feedback quality for future sessions',
        message: 'High-confidence feedback usually means no missed drinks, clear timing, and no blackout, vomiting, or memory gap.',
        supporting_reasons: summary.sessions_with_unusable_calibration > 0
          ? ['Feedback exists, but calibration was unavailable for the saved feedback.']
          : ['Feedback exists, but no usable calibration signal is recorded yet.'],
        recommended_steps: [
          'Log each drink near the time it happens.',
          'Only mark feedback high-confidence when drink count and timing are clear.',
          'Sessions with vomiting, blackout, or memory gaps are kept as feedback, not calibration.'
        ],
        href: 'history.html',
        cta_label: 'Review feedback',
        priority: 'medium'
      });
    }

    if (summary.sessions_with_usable_calibration === 1) {
      return Object.assign({}, base, {
        action: 'continue_high_confidence_feedback',
        title: 'Continue adding high-confidence feedback',
        message: 'One usable calibration signal exists. More high-confidence sessions can make the limited estimate adjustment more stable.',
        supporting_reasons: ['One usable limited beta calibration signal is saved.'],
        recommended_steps: [
          'Keep logging drink timing clearly.',
          'Add feedback only when session context is reliable.',
          'Remember this does not determine legal or medical sobriety.'
        ],
        href: 'bac-calculator.html',
        cta_label: 'Log another session',
        priority: 'low'
      });
    }

    if (summary.sessions_with_usable_calibration > 1 && summary.latest_personalization_active) {
      return Object.assign({}, base, {
        action: 'limited_personalization_active',
        title: 'Limited personalization is active',
        message: 'High-confidence feedback is being used only for elimination-rate estimate adjustment.',
        supporting_reasons: ['Multiple usable calibration signals are saved.', 'The latest prediction reports active limited personalization.'],
        recommended_steps: [
          'Continue logging sessions consistently.',
          'Keep feedback high-confidence when possible.',
          'Treat every BAC value as an estimate, not legal or medical guidance.'
        ],
        href: 'history.html',
        cta_label: 'View history',
        priority: 'low'
      });
    }

    return Object.assign({}, base, {
      action: 'continue_high_confidence_feedback',
      title: 'Continue high-confidence feedback',
      message: 'Usable calibration signals are saved. Future high-confidence sessions can continue supporting limited estimate adjustment.',
      supporting_reasons: ['Usable limited beta calibration signals are saved.'],
      recommended_steps: [
        'Keep drink counts and timing clear.',
        'Add feedback when you remember the session context.',
        'Do not use estimates for legal or medical decisions.'
      ],
      href: 'history.html',
      cta_label: 'View history',
      priority: 'low'
    });
  }

  function formatEvidenceDate(iso) {
    if (!iso) return '—';
    var date = new Date(iso);
    if (!Number.isFinite(date.getTime())) return '—';
    try {
      return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    } catch(e) {
      return iso;
    }
  }

  function evidenceStatusLabel(status) {
    if (status === 'usable_calibration') return 'Used for limited personalization';
    if (status === 'calibration_unavailable') return 'Saved, not used for calibration';
    if (status === 'no_calibration_signal_recorded') return 'No calibration signal recorded';
    return 'Feedback saved';
  }

  function getPersonalizationEvidenceRows(options) {
    options = options && typeof options === 'object' ? options : {};
    var includeNoFeedback = options.include_no_feedback === true;
    return getSessions().reduce(function(rows, session) {
      var state = getSessionCalibrationState(session);
      if (!state.has_feedback && !includeNoFeedback) return rows;
      var review = session.post_session_review || {};
      var result = review.implied_beta_result || null;
      var usable = !!state.has_usable_calibration;
      var beta = usable && result ? finiteNumber(result.implied_beta) : null;
      rows.push({
        session_id: session.session_id || '',
        started_at: session.started_at || null,
        completed_at: session.ended_at || session.updated_at || null,
        display_date: formatEvidenceDate(session.ended_at || session.started_at || session.updated_at),
        has_feedback: state.has_feedback,
        calibration_status: state.calibration_status,
        calibration_status_label: evidenceStatusLabel(state.calibration_status),
        calibration_message: state.calibration_message,
        rejection_reasons: state.rejection_reasons.slice(),
        usable_for_calibration: usable,
        implied_beta: beta,
        beta_source_label: usable ? 'Explicit usable limited beta metadata' : 'Not used for calibration',
        drink_log_confidence: review.drink_log_confidence || 'unknown',
        drink_timing_confidence: review.drink_timing_confidence || review.timing_confidence || 'unknown',
        missed_drinks: review.missed_drinks || 'unknown',
        blackout: review.blackout === true,
        vomited: review.vomited === true,
        memory_gap: review.memory_gap === true
      });
      return rows;
    }, []).sort(function(a, b) {
      var tb = new Date(b.completed_at || b.started_at || 0).getTime();
      var ta = new Date(a.completed_at || a.started_at || 0).getTime();
      return tb - ta;
    });
  }

  function getPersonalizationReliabilitySummary() {
    var summary = getPersonalizationProfileSummary();
    var evidence = getPersonalizationEvidenceRows();
    var action = getPersonalizationNextBestAction(summary);
    var usable = evidence.filter(function(row) { return row.usable_for_calibration; }).length;
    var unusable = evidence.filter(function(row) { return row.calibration_status === 'calibration_unavailable'; }).length;
    var noSignal = evidence.filter(function(row) { return row.calibration_status === 'no_calibration_signal_recorded'; }).length;
    var totalFeedback = evidence.length;
    var level = 'none';
    var label = 'No personalization evidence yet';
    var message = 'No feedback evidence is available for limited elimination-rate calibration.';
    var limitingFactors = [];
    var strengths = [];

    if (!summary.profile_completed && summary.total_sessions === 0) {
      limitingFactors.push('Baseline profile is incomplete or missing.');
      limitingFactors.push('No completed sessions are saved yet.');
    } else if (usable === 0 && totalFeedback === 0) {
      level = 'baseline_only';
      label = 'Baseline estimate only';
      message = 'The app is using the baseline elimination estimate because no usable feedback calibration signal is saved.';
      if (!summary.profile_completed) limitingFactors.push('Baseline profile is incomplete or missing.');
      if (summary.completed_sessions === 0) limitingFactors.push('No completed sessions are saved yet.');
      else limitingFactors.push('No post-session feedback is saved yet.');
      if (summary.profile_completed) strengths.push('Baseline profile is saved.');
      if (summary.completed_sessions > 0) strengths.push('Completed sessions are saved.');
    } else if (usable === 0 && totalFeedback > 0) {
      level = 'feedback_saved_no_calibration';
      label = 'Feedback saved, no usable calibration yet';
      message = 'Feedback is saved as context, but no session has an explicit usable calibration signal.';
      if (unusable > 0) limitingFactors.push('Some feedback was saved but excluded from calibration.');
      if (noSignal > 0) limitingFactors.push('Some feedback has no calibration signal recorded.');
      strengths.push('Post-session feedback is saved.');
    } else if (usable === 1) {
      level = 'limited_single_signal';
      label = 'Limited, one usable signal';
      message = 'Limited personalization is supported by one high-confidence feedback session.';
      strengths.push('One explicit usable calibration signal is saved.');
      if (unusable > 0 || noSignal > 0) limitingFactors.push('Additional feedback exists but is not usable for calibration.');
    } else if (usable > 1 && unusable > usable) {
      level = 'limited_but_mixed_quality';
      label = 'Limited, mixed feedback quality';
      message = 'Some sessions help limited calibration, while several saved feedback sessions are excluded or have no signal.';
      strengths.push('Multiple usable calibration signals are saved.');
      limitingFactors.push('Rejected or no-signal feedback outnumbers usable signals.');
    } else if (usable > 1) {
      level = 'limited_multi_signal';
      label = 'Limited, multiple usable signals';
      message = 'Limited personalization is supported by multiple high-confidence feedback sessions.';
      strengths.push('Multiple explicit usable calibration signals are saved.');
      if (unusable > 0 || noSignal > 0) limitingFactors.push('Some feedback is saved but not used for calibration.');
    }

    return {
      reliability_level: level,
      reliability_label: label,
      reliability_message: message,
      usable_signal_count: usable,
      unusable_signal_count: unusable,
      no_signal_feedback_count: noSignal,
      total_feedback_count: totalFeedback,
      active_personalization: summary.latest_personalization_active,
      limiting_factors: limitingFactors,
      strengths: strengths,
      recommended_next_step: action ? action.title : 'No next step available.'
    };
  }

  /* ── Export ── */
  global.SaferSessionStorage = {
    STORAGE_KEY: STORAGE_KEY,
    ACTIVE_SESSION_KEY: ACTIVE_KEY,
    PROFILE_KEY: PROFILE_KEY,
    PERSONALIZATION_SETTINGS_KEY: PERSONALIZATION_SETTINGS_KEY,
    getSessions: getSessions,
    saveSessions: saveSessions,
    getPersonalizationSettings: getPersonalizationSettings,
    savePersonalizationSettings: savePersonalizationSettings,
    isLimitedPersonalizationEnabled: isLimitedPersonalizationEnabled,
    clearPersonalizationSettings: clearPersonalizationSettings,
    resetPersonalizationSettingsToDefault: resetPersonalizationSettingsToDefault,
    clearPersonalizationPredictionSnapshots: clearPersonalizationPredictionSnapshots,
    clearCalibrationEvidence: clearCalibrationEvidence,
    clearAllPersonalizationData: clearAllPersonalizationData,
    createSession: createSession,
    getSessionById: getSessionById,
    updateSession: updateSession,
    deleteSession: deleteSession,
    getActiveDraftSession: getActiveDraftSession,
    getOrCreateActiveDraftSession: getOrCreateActiveDraftSession,
    setActiveDraftSessionId: setActiveDraftSessionId,
    clearActiveDraftSessionId: clearActiveDraftSessionId,
    addEventToSession: addEventToSession,
    completeSession: completeSession,
    isReviewPending: isReviewPending,
    getSessionsPendingReview: getSessionsPendingReview,
    savePostSessionReview: savePostSessionReview,
    markReviewCompleted: markReviewCompleted,
    getProfile: getProfile,
    saveProfile: saveProfile,
    getAllImpliedBetas: getAllImpliedBetas,
    latestPredictionSnapshot: latestPredictionSnapshot,
    getPredictionPersonalizationState: getPredictionPersonalizationState,
    getSessionCalibrationState: getSessionCalibrationState,
    getPersonalizationProfileSummary: getPersonalizationProfileSummary,
    getPersonalizationNextBestAction: getPersonalizationNextBestAction,
    getPersonalizationEvidenceRows: getPersonalizationEvidenceRows,
    getPersonalizationReliabilitySummary: getPersonalizationReliabilitySummary,
  };
})(typeof window !== 'undefined' ? window : this);
