/**
 * Session list persistence (separate from profile: safer_user_profile).
 * Active working draft is tracked via safer_active_session_id.
 */
(function (global) {
  var STORAGE_KEY = 'safer_sessions';
  var ACTIVE_KEY = 'safer_active_session_id';

  function genSessionId() {
    if (global.crypto && typeof global.crypto.randomUUID === 'function') {
      return global.crypto.randomUUID();
    }
    return 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
  }

  function defaultSessionShape() {
    var now = new Date().toISOString();
    return {
      schema_version: 1,
      session_id: genSessionId(),
      title: 'Drinking session - ' + new Date().toLocaleString(),
      user_id: null,
      status: 'draft',
      started_at: now,
      updated_at: now,
      ended_at: null,
      events: [],
      review_status: 'pending',
      post_session_review: null,
      inputs: {
        drinks: 0,
        drink_type: 'standard',
        hours_elapsed: 0,
        food_intake: 'unknown',
        hydration: 'unknown',
        sleep: 'unknown',
        fasting: 'unknown'
      },
      feedback: {
        perceived_intoxication: null,
        hangover_severity: null,
        blackout: null,
        vomiting: null
      }
    };
  }

  function ensureSessionShape(session) {
    if (!session || typeof session !== 'object') return defaultSessionShape();
    if (!Array.isArray(session.events)) session.events = [];
    if (!session.title) session.title = 'Drinking session - ' + new Date(session.started_at || Date.now()).toLocaleString();
    if (!session.review_status) session.review_status = 'pending';
    if (session.post_session_review && typeof session.post_session_review !== 'object') {
      session.post_session_review = null;
    }
    if (session.post_session_review) {
      session.review_status = 'completed';
    } else if (session.status === 'completed') {
      session.review_status = 'pending';
    }
    if (!session.inputs || typeof session.inputs !== 'object') session.inputs = defaultSessionShape().inputs;
    if (!session.feedback || typeof session.feedback !== 'object') session.feedback = defaultSessionShape().feedback;
    if (session.schema_version == null) session.schema_version = 1;
    return session;
  }

  function isReviewPending(session) {
    session = ensureSessionShape(session);
    return session.status === 'completed' &&
      session.review_status !== 'completed' &&
      !session.post_session_review;
  }

  function deepMergeInputsFeedback(base, overrides) {
    if (!overrides || typeof overrides !== 'object') return base;
    if (overrides.inputs && typeof overrides.inputs === 'object') {
      Object.assign(base.inputs, overrides.inputs);
    }
    if (overrides.feedback && typeof overrides.feedback === 'object') {
      Object.assign(base.feedback, overrides.feedback);
    }
    return base;
  }

  function getSessions() {
    try {
      var raw = global.localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.map(function (s) { return ensureSessionShape(s); });
    } catch (e) {
      return [];
    }
  }

  function saveSessions(sessions) {
    if (!Array.isArray(sessions)) {
      throw new TypeError('saveSessions expects an array');
    }
    global.localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  }

  /**
   * Creates a new draft session, appends it, sets it as the active draft, and returns it.
   * Optional partial may include inputs / feedback objects to merge.
   */
  function createSession(partial) {
    var base = defaultSessionShape();
    deepMergeInputsFeedback(base, partial);
    if (partial && typeof partial === 'object') {
      if (partial.title) base.title = String(partial.title);
      if (Array.isArray(partial.events)) base.events = partial.events.slice();
      if (partial.review_status) base.review_status = String(partial.review_status);
      if (partial.post_session_review && typeof partial.post_session_review === 'object') {
        base.post_session_review = normalizePostSessionReview(partial.post_session_review);
        base.review_status = 'completed';
      }
    }
    base.updated_at = base.started_at;
    var all = getSessions();
    all.push(base);
    saveSessions(all);
    try {
      global.localStorage.setItem(ACTIVE_KEY, base.session_id);
    } catch (e2) { /* ignore */ }
    return base;
  }

  function getSessionById(sessionId) {
    if (!sessionId) return null;
    var all = getSessions();
    for (var i = 0; i < all.length; i++) {
      if (all[i].session_id === sessionId) return all[i];
    }
    return null;
  }

  /** Replace one session in the array by session_id. */
  function updateSession(updated) {
    ensureSessionShape(updated);
    var all = getSessions();
    var idx = -1;
    for (var i = 0; i < all.length; i++) {
      if (all[i].session_id === updated.session_id) {
        idx = i;
        break;
      }
    }
    if (idx === -1) return false;
    all[idx] = updated;
    saveSessions(all);
    return true;
  }

  function deleteSession(sessionId) {
    if (!sessionId) {
      return { deleted: false, session_id: null, was_active: false };
    }
    var all = getSessions();
    var kept = [];
    var deleted = null;
    for (var i = 0; i < all.length; i++) {
      if (all[i].session_id === sessionId) {
        deleted = all[i];
      } else {
        kept.push(all[i]);
      }
    }
    if (!deleted) {
      return { deleted: false, session_id: sessionId, was_active: false };
    }

    var wasActive = false;
    try {
      wasActive = global.localStorage.getItem(ACTIVE_KEY) === sessionId;
    } catch (e) { /* ignore */ }

    saveSessions(kept);
    if (wasActive) clearActiveDraftSessionId();

    return {
      deleted: true,
      session_id: sessionId,
      was_active: wasActive,
      deleted_session: deleted
    };
  }

  function getActiveDraftSession() {
    try {
      var id = global.localStorage.getItem(ACTIVE_KEY);
      if (!id) return null;
      var s = getSessionById(id);
      if (s && s.status === 'draft') return s;
      global.localStorage.removeItem(ACTIVE_KEY);
      return null;
    } catch (e) {
      return null;
    }
  }

  function setActiveDraftSessionId(sessionId) {
    if (sessionId) global.localStorage.setItem(ACTIVE_KEY, sessionId);
    else global.localStorage.removeItem(ACTIVE_KEY);
  }

  function clearActiveDraftSessionId() {
    try {
      global.localStorage.removeItem(ACTIVE_KEY);
    } catch (e) { /* ignore */ }
  }

  function getOrCreateActiveDraftSession(partial) {
    var active = getActiveDraftSession();
    if (active) return active;
    return createSession(partial || {});
  }

  function genEventId() {
    if (global.crypto && typeof global.crypto.randomUUID === 'function') {
      return global.crypto.randomUUID();
    }
    return 'evt_' + Date.now() + '_' + Math.random().toString(36).slice(2, 9);
  }

  function addEventToSession(sessionId, event) {
    if (!sessionId) return null;
    var session = getSessionById(sessionId);
    if (!session) return null;
    ensureSessionShape(session);
    var nowIso = new Date().toISOString();
    var evt = Object.assign(
      {
        event_id: genEventId(),
        event_type: 'other',
        timestamp: nowIso,
      },
      event || {}
    );
    session.events.push(evt);
    session.updated_at = nowIso;
    updateSession(session);
    return session;
  }

  function completeSession(sessionId) {
    if (!sessionId) return null;
    var session = getSessionById(sessionId);
    if (!session) return null;
    ensureSessionShape(session);
    var nowIso = new Date().toISOString();
    session.status = 'completed';
    if (!session.post_session_review) session.review_status = 'pending';
    session.ended_at = nowIso;
    session.updated_at = nowIso;
    updateSession(session);
    clearActiveDraftSessionId();
    return session;
  }

  function clampInt(value, lower, upper, fallback) {
    var n = parseInt(value, 10);
    if (!Number.isFinite(n)) n = fallback;
    return Math.max(lower, Math.min(upper, n));
  }

  function optionalNumber(value) {
    if (value === '' || value == null) return null;
    var n = Number(value);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }

  function normalizeHydration(value) {
    var allowed = { unknown: true, low: true, normal: true, high: true };
    var v = String(value || 'unknown').toLowerCase();
    return allowed[v] ? v : 'unknown';
  }

  function normalizePostSessionReview(review) {
    var raw = review && typeof review === 'object' ? review : {};
    return {
      submitted_at: raw.submitted_at || new Date().toISOString(),
      hangover_severity: clampInt(raw.hangover_severity, 0, 5, 0),
      perceived_peak_intoxication: clampInt(raw.perceived_peak_intoxication, 0, 5, 0),
      vomited: raw.vomited === true,
      blackout: raw.blackout === true,
      memory_gap: raw.memory_gap === true,
      felt_sober_time: String(raw.felt_sober_time || '').trim(),
      sleep_hours_after: optionalNumber(raw.sleep_hours_after),
      hydration_after: normalizeHydration(raw.hydration_after),
      notes: String(raw.notes || '').trim()
    };
  }

  function getSessionsPendingReview() {
    return getSessions().filter(function (session) {
      return isReviewPending(session);
    });
  }

  function markReviewCompleted(sessionId) {
    if (!sessionId) return null;
    var session = getSessionById(sessionId);
    if (!session) return null;
    ensureSessionShape(session);
    if (!session.post_session_review) return session;
    var nowIso = new Date().toISOString();
    session.review_status = 'completed';
    session.updated_at = nowIso;
    updateSession(session);
    return session;
  }

  function savePostSessionReview(sessionId, review) {
    if (!sessionId) return null;
    var session = getSessionById(sessionId);
    if (!session) return null;
    ensureSessionShape(session);
    if (session.status !== 'completed') return null;

    // Post-session review is subjective feedback, not a direct BAC measurement.
    // It is stored for future personalization or impairment-risk calibration,
    // and it must not currently modify BAC predictions, r, or beta.
    session.post_session_review = normalizePostSessionReview(review);
    session.review_status = 'completed';
    session.updated_at = session.post_session_review.submitted_at;
    updateSession(session);
    return session;
  }

  global.SaferSessionStorage = {
    STORAGE_KEY: STORAGE_KEY,
    ACTIVE_SESSION_KEY: ACTIVE_KEY,
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
    markReviewCompleted: markReviewCompleted
  };
})(typeof window !== 'undefined' ? window : this);
