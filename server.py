"""Lightweight HTTP API for BAC prediction endpoints.

Endpoints:
    POST /predict          — Full BAC prediction with Bayesian beta personalization
    POST /r-coefficient    — r estimation only (legacy compatibility)

Run locally:
    python3 server.py
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from BACCalculator import (
    calculate_bac_range,
    estimate_beta,
    implied_beta_from_session,
    population_beta_prior,
    r_coefficient,
    PRIOR_SESSION_WEIGHT,
)


HOST  = "0.0.0.0"
PORT  = 8000
MODEL_NAME            = "widmark-bayesian-scaffold-v2"
MODEL_STATUS          = "scaffold"
COEFFICIENT_SOURCE    = "nhanes_derived_linear_regression"
PERSONALIZATION_STATUS_ACTIVE  = "bayesian_shrinkage_active"
PERSONALIZATION_STATUS_NONE    = "not_enabled"


# ── Helpers ───────────────────────────────────────────────────────────────

def _json_error(message: str, status: int = 400) -> tuple[dict[str, Any], int]:
    return {"error": {"message": message, "status": status}}, status

def _as_float(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")
    return float(value)

def _as_float_optional(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default

def _body_fat_bracket_from_percent(body_fat_percent: float) -> str:
    if body_fat_percent < 15:  return "low"
    if body_fat_percent <= 25: return "mid"
    return "high"


# ── /predict logic ────────────────────────────────────────────────────────

def predict_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate request payload and return a full Bayesian-updated BAC prediction.

    Request shape:
    {
      "profile": {
        "sex":              "male" | "female" | "other",
        "age_years":        number,
        "height_cm":        number,
        "weight_kg":        number,
        "body_fat_bracket": "low" | "mid" | "high",   // optional
        "body_fat_percent": number,                     // optional, auto-brackets
        "drinks_per_week":  number                      // optional, default 0
      },
      "session": {
        "standard_drinks": number,   // required if grams_alcohol absent
        "grams_alcohol":   number,   // required if standard_drinks absent
        "hours_elapsed":   number
      },
      "history": {                                      // optional
        "session_implied_betas": [number, ...]          // back-calculated from past reviews
      }
    }

    The history.session_implied_betas list should contain values produced by
    implied_beta_from_session() for each completed + reviewed past session.
    The Bayesian shrinkage estimator weights these against the demographic prior.
    """
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    profile = payload.get("profile")
    session = payload.get("session")
    history = payload.get("history", {})

    if not isinstance(profile, dict):
        raise ValueError("profile is required and must be an object.")
    if not isinstance(session, dict):
        raise ValueError("session is required and must be an object.")
    if not isinstance(history, dict):
        history = {}

    # ── profile fields ────────────────────────────────────────────────────
    sex      = profile.get("sex", "other")
    age      = _as_float(profile.get("age_years"),  "profile.age_years")
    height   = _as_float(profile.get("height_cm"),  "profile.height_cm")
    weight   = _as_float(profile.get("weight_kg"),  "profile.weight_kg")
    dpw      = _as_float_optional(profile.get("drinks_per_week"), 0.0)

    fat_bracket = profile.get("body_fat_bracket")
    fat_pct     = profile.get("body_fat_percent")
    if fat_bracket is None and isinstance(fat_pct, (int, float)):
        fat_bracket = _body_fat_bracket_from_percent(float(fat_pct))

    # ── session fields ────────────────────────────────────────────────────
    standard_drinks = session.get("standard_drinks")
    grams_alcohol   = session.get("grams_alcohol")
    hours_elapsed   = _as_float(session.get("hours_elapsed"), "session.hours_elapsed")

    if grams_alcohol is None:
        if standard_drinks is None:
            raise ValueError("session.grams_alcohol or session.standard_drinks is required.")
        standard_drinks = _as_float(standard_drinks, "session.standard_drinks")
        if standard_drinks < 0:
            raise ValueError("session.standard_drinks cannot be negative.")
        grams_alcohol = standard_drinks * 14.0
    else:
        grams_alcohol = _as_float(grams_alcohol, "session.grams_alcohol")

    # ── validation ────────────────────────────────────────────────────────
    if age    <= 0: raise ValueError("profile.age_years must be positive.")
    if height <= 0: raise ValueError("profile.height_cm must be positive.")
    if weight <= 0: raise ValueError("profile.weight_kg must be positive.")
    if grams_alcohol < 0:  raise ValueError("session.grams_alcohol cannot be negative.")
    if hours_elapsed < 0:  raise ValueError("session.hours_elapsed cannot be negative.")

    # ── r estimation (regression) ─────────────────────────────────────────
    r = r_coefficient(
        gender=str(sex),
        age=age,
        weight=weight,
        height=height,
        fat=fat_bracket,
    )

    # ── beta estimation (demographic prior + Bayesian shrinkage) ──────────
    session_implied_betas = history.get("session_implied_betas", [])
    if not isinstance(session_implied_betas, list):
        session_implied_betas = []

    # Filter to valid numeric values
    valid_implied = [
        float(b) for b in session_implied_betas
        if isinstance(b, (int, float)) and b > 0
    ]

    beta_per_hour = estimate_beta(
        profile={
            "age":             age,
            "weight_kg":       weight,
            "height_cm":       height,
            "drinks_per_week": dpw,
        },
        session_history=valid_implied if valid_implied else None,
    )

    # ── BAC range ─────────────────────────────────────────────────────────
    bac = calculate_bac_range(
        alc_g=grams_alcohol,
        weight_kg=weight,
        r=r,
        beta_per_hour=beta_per_hour,
        hours_elapsed=hours_elapsed,
    )

    # ── personalization metadata ──────────────────────────────────────────
    n_sessions          = len(valid_implied)
    prior_weight_pct    = round(PRIOR_SESSION_WEIGHT / (PRIOR_SESSION_WEIGHT + n_sessions) * 100, 1) if n_sessions else 100.0
    personal_weight_pct = round(100.0 - prior_weight_pct, 1)
    personalization_status = (
        PERSONALIZATION_STATUS_ACTIVE if n_sessions > 0 else PERSONALIZATION_STATUS_NONE
    )

    return {
        "schema_version": 2,
        "units": {
            "bac":          "display_decimal_0_08_means_0_08_percent",
            "beta_per_hour":"bac_display_units_per_hour",
            "weight":       "kg",
            "height":       "cm",
            "alcohol":      "grams_ethanol",
            "time":         "hours",
        },
        "model": {
            "name":                MODEL_NAME,
            "status":              MODEL_STATUS,
            "r":                   round(r, 6),
            "beta_per_hour":       round(beta_per_hour, 6),
            "coefficient_source":  COEFFICIENT_SOURCE,
            "personalization":     personalization_status,
            "sessions_used":       n_sessions,
            "prior_weight_pct":    prior_weight_pct,
            "personal_weight_pct": personal_weight_pct,
        },
        "bac": {
            "low":      round(float(bac["low"]),      6),
            "estimate": round(float(bac["estimate"]), 6),
            "high":     round(float(bac["high"]),     6),
        },
        "meta": {
            "disclaimer": (
                "Estimate only; not legal or medical advice. "
                "Do not use this estimate to make driving decisions."
            )
        },
    }


def implied_beta_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Compute a session-implied beta to store after a post-session review.

    Request shape:
    {
      "grams_alcohol":    number,
      "weight_kg":        number,
      "r":                number,
      "felt_sober_hours": number
    }

    Call this after a user submits their post-session review (when they indicate
    approximately when they felt sober). Store the returned implied_beta in
    the user's profile history to feed into future /predict calls.
    """
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    grams    = _as_float(payload.get("grams_alcohol"),    "grams_alcohol")
    weight   = _as_float(payload.get("weight_kg"),        "weight_kg")
    r        = _as_float(payload.get("r"),                "r")
    sober_hr = _as_float(payload.get("felt_sober_hours"), "felt_sober_hours")

    if grams  < 0:  raise ValueError("grams_alcohol cannot be negative.")
    if weight <= 0: raise ValueError("weight_kg must be positive.")
    if r      <= 0: raise ValueError("r must be positive.")
    if sober_hr <= 0: raise ValueError("felt_sober_hours must be positive.")

    from BACCalculator import implied_beta_from_session
    implied = implied_beta_from_session(grams, weight, r, sober_hr)

    if implied is None:
        raise ValueError("Could not compute implied beta from provided inputs.")

    return {
        "implied_beta":  round(implied, 6),
        "instructions":  (
            "Store this value in history.session_implied_betas and include "
            "the full list in future /predict requests to enable Bayesian personalization."
        ),
    }


# ── HTTP handler ──────────────────────────────────────────────────────────

class BACRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # suppress default request logs
        pass

    def _send_json(self, body: dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",                  "application/json")
        self.send_header("Access-Control-Allow-Origin",   "*")
        self.send_header("Access-Control-Allow-Headers",  "Content-Type")
        self.send_header("Access-Control-Allow-Methods",  "POST, OPTIONS")
        self.send_header("Content-Length",                str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw    = self.rfile.read(length).decode("utf-8")
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return None

    def do_POST(self) -> None:  # noqa: N802
        data = self._read_json()
        if data is None:
            body, status = _json_error("Request body must be valid JSON.", 400)
            self._send_json(body, status)
            return

        routes = {
            "/predict":         (predict_from_payload,        data),
            "/implied-beta":    (implied_beta_from_payload,   data),
            "/r-coefficient":   (self._handle_r_coefficient,  data),
        }

        if self.path in routes:
            fn, arg = routes[self.path]
            try:
                result = fn(arg)
                self._send_json(result, 200)
            except ValueError as exc:
                body, status = _json_error(str(exc), 400)
                self._send_json(body, status)
        else:
            body, status = _json_error("Route not found.", 404)
            self._send_json(body, status)

    def _handle_r_coefficient(self, payload: dict) -> dict:
        r = r_coefficient(
            gender=payload.get("gender"),
            age   =_as_float(payload.get("age"),    "age"),
            weight=_as_float(payload.get("weight"), "weight"),
            height=_as_float(payload.get("height"), "height"),
            fat   =payload.get("fat"),
        )
        return {"r": round(r, 6)}


def run_server() -> None:
    server = HTTPServer((HOST, PORT), BACRequestHandler)
    print(f"BAC API listening at http://{HOST}:{PORT}")
    print(f"  POST /predict        — BAC prediction (Bayesian personalization)")
    print(f"  POST /implied-beta   — Back-calculate session beta for review storage")
    print(f"  POST /r-coefficient  — r estimation only (legacy)")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
