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
      user_id: null,
      status: 'draft',
      started_at: now,
      updated_at: now,
      ended_at: null,
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
      return Array.isArray(parsed) ? parsed : [];
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

  global.SaferSessionStorage = {
    STORAGE_KEY: STORAGE_KEY,
    ACTIVE_SESSION_KEY: ACTIVE_KEY,
    getSessions: getSessions,
    saveSessions: saveSessions,
    createSession: createSession,
    getSessionById: getSessionById,
    updateSession: updateSession,
    getActiveDraftSession: getActiveDraftSession,
    setActiveDraftSessionId: setActiveDraftSessionId,
    clearActiveDraftSessionId: clearActiveDraftSessionId
  };
})(typeof window !== 'undefined' ? window : this);
