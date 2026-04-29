/**
 * SaferSessionStorage — session list + profile persistence.
 * Keys: safer_sessions, safer_active_session_id, safer_user_profile
 */
(function (global) {
  var STORAGE_KEY = 'safer_sessions';
  var ACTIVE_KEY  = 'safer_active_session_id';
  var PROFILE_KEY = 'safer_user_profile';

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
    return {
      submitted_at: raw.submitted_at || new Date().toISOString(),
      hangover_severity: clampInt(raw.hangover_severity, 0, 5, 0),
      perceived_peak_intoxication: clampInt(raw.perceived_peak_intoxication, 0, 5, 0),
      vomited: raw.vomited === true,
      blackout: raw.blackout === true,
      memory_gap: raw.memory_gap === true,
      felt_sober_hours: optNum(raw.felt_sober_hours),   // numeric now
      felt_sober_time: String(raw.felt_sober_time || '').trim(),
      food_intake: normFood(raw.food_intake),
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

      if (isPlausibleBeta(review.implied_beta) && !review.vomited && !review.blackout) {
        acc.push({
          implied_beta: review.implied_beta,
          usable_for_personalization: true,
          confidence: null,
          source_session_id: s.session_id,
          legacy: true
        });
        seen[s.session_id] = true;
      }
      return acc;
    }, []);
  }

  /* ── Export ── */
  global.SaferSessionStorage = {
    STORAGE_KEY: STORAGE_KEY,
    ACTIVE_SESSION_KEY: ACTIVE_KEY,
    PROFILE_KEY: PROFILE_KEY,
    getSessions: getSessions,
    saveSessions: saveSessions,
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
  };
})(typeof window !== 'undefined' ? window : this);
