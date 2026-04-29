"""Lightweight HTTP API for BAC prediction endpoints.

Endpoints:
    POST /predict          — Full BAC prediction with Bayesian beta personalization
    POST /r-coefficient    — r estimation only (legacy compatibility)

Run locally:
    python3 server.py
"""

from __future__ import annotations

import json
import math
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from BayesianStats import estimate_personalized_beta
from BACCalculator import (
    calculate_bac_range,
    generate_event_aware_bac_curve,
    generate_legacy_bac_curve,
    MAX_BETA_PER_HOUR,
    MIN_BETA_PER_HOUR,
    population_beta_prior,
    r_coefficient,
)
from reversebeta import estimate_implied_beta_from_session


HOST  = "0.0.0.0"
PORT  = 8000
MODEL_NAME            = "widmark-bayesian-scaffold-v2"
MODEL_STATUS          = "scaffold"
COEFFICIENT_SOURCE    = "nhanes_derived_linear_regression"
PERSONALIZATION_STATUS_ACTIVE  = "bayesian_shrinkage_active"
PERSONALIZATION_STATUS_NONE    = "not_enabled"
MIN_BODY_FAT_PERCENT  = 3.0
MAX_BODY_FAT_PERCENT  = 65.0


# ── Helpers ───────────────────────────────────────────────────────────────

def _json_error(message: str, status: int = 400) -> tuple[dict[str, Any], int]:
    return {"error": {"message": message, "status": status}}, status

def _as_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a number.")
    return float(value)

def _as_float_optional(value: Any, default: float) -> float:
    if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return default

def _first_present(mapping: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in mapping:
            return mapping.get(name)
    return None

def body_fat_bucket_from_percent(body_fat_percent: float) -> str:
    """Map noisy user-entered body-fat percent to universal model buckets.

    These are internal robustness buckets, not medical or fitness categories.
    Sex already selects the r formula branch, so the bucket thresholds are
    intentionally universal to avoid double-counting sex-based assumptions.
    """
    if body_fat_percent < 15.0:  return "low"
    if body_fat_percent <= 25.0: return "mid"
    return "high"

def _normalize_legacy_body_fat_bracket(value: Any) -> str:
    if value is None:
        return "high"
    normalized = str(value).strip().lower()
    if normalized == "low": return "low"
    if normalized in {"mid", "medium"}: return "mid"
    return "high"

def derive_body_fat_bracket(profile: dict[str, Any]) -> str:
    """Derive the internal r-model fat bucket from API profile data.

    body_fat_percent is the backend source of truth when present. Legacy
    body_fat_bracket remains supported only when percent is absent.
    """
    fat_pct = profile.get("body_fat_percent")
    if fat_pct is not None:
        percent = _as_float(fat_pct, "profile.body_fat_percent")
        if percent < MIN_BODY_FAT_PERCENT or percent > MAX_BODY_FAT_PERCENT:
            raise ValueError(
                f"profile.body_fat_percent must be between "
                f"{MIN_BODY_FAT_PERCENT:g} and {MAX_BODY_FAT_PERCENT:g}."
            )
        return body_fat_bucket_from_percent(percent)

    return _normalize_legacy_body_fat_bracket(profile.get("body_fat_bracket"))

def _extract_beta_history(history: dict[str, Any]) -> tuple[list[Any], int, list[str]]:
    """Extract old numeric and new metadata-rich implied beta observations."""
    warnings: list[str] = []
    api_excluded = 0
    entries = history.get("session_implied_betas", [])
    if entries is None:
        return [], 0, warnings
    if not isinstance(entries, list):
        return [], 1, ["history_session_implied_betas_not_list"]

    observations: list[Any] = []
    for entry in entries:
        if isinstance(entry, dict):
            nested = entry.get("implied_beta_result")
            if nested is not None and not isinstance(nested, dict):
                api_excluded += 1
                continue

            usable_values = []
            if "usable_for_personalization" in entry:
                usable_values.append(entry.get("usable_for_personalization"))
            if isinstance(nested, dict) and "usable_for_personalization" in nested:
                usable_values.append(nested.get("usable_for_personalization"))
            if usable_values and True not in usable_values:
                api_excluded += 1
                continue

            beta_value = entry.get("implied_beta", entry.get("beta"))
            if isinstance(nested, dict):
                beta_value = nested.get("implied_beta", nested.get("beta", beta_value))
            observations.append(beta_value)
            continue

        observations.append(entry)

    return observations, api_excluded, warnings

def _beta_metadata_response(beta_result: dict[str, Any], api_excluded: int, warnings: list[str]) -> dict[str, Any]:
    sessions_excluded = int(beta_result.get("sessions_excluded", 0)) + api_excluded
    combined_warnings = list(beta_result.get("warnings", [])) + warnings
    return {
        "value": round(float(beta_result["beta"]), 6),
        "source": beta_result.get("source"),
        "population_beta": round(float(beta_result["population_beta"]), 6),
        "sessions_used": int(beta_result.get("sessions_used", 0)),
        "sessions_excluded": sessions_excluded,
        "observed_mean": (
            None if beta_result.get("observed_mean") is None
            else round(float(beta_result["observed_mean"]), 6)
        ),
        "observed_sd": (
            None if beta_result.get("observed_sd") is None
            else round(float(beta_result["observed_sd"]), 6)
        ),
        "posterior_beta": (
            None if beta_result.get("posterior_beta") is None
            else round(float(beta_result["posterior_beta"]), 6)
        ),
        "personal_weight": round(float(beta_result.get("personal_weight", 0.0)), 6),
        "population_weight": round(float(beta_result.get("population_weight", 1.0)), 6),
        "population_blend_weight": round(float(beta_result.get("population_blend_weight", 0.0)), 6),
        "min_beta": float(beta_result.get("min_beta", MIN_BETA_PER_HOUR)),
        "max_beta": float(beta_result.get("max_beta", MAX_BETA_PER_HOUR)),
        "warnings": combined_warnings,
    }

def _extract_drink_events_for_implied_beta(payload: dict[str, Any]) -> tuple[list[Any], list[Any], list[str]]:
    warnings: list[str] = []
    drink_events = payload.get("drink_events")

    if drink_events is None:
        grams = _first_present(payload, ["grams_alcohol", "grams", "alcohol_grams"])
        if grams is None:
            raise ValueError("drink_events or grams_alcohol is required.")
        warnings.append("legacy_payload_no_event_timing")
        return [grams], [0.0], warnings

    if not isinstance(drink_events, list):
        raise ValueError("drink_events must be a list.")
    if not drink_events:
        raise ValueError("drink_events must contain at least one event.")

    grams_by_drink: list[Any] = []
    drink_times: list[Any] = []
    for event in drink_events:
        if not isinstance(event, dict):
            raise ValueError("Each drink event must be an object.")
        grams_by_drink.append(_first_present(event, ["grams_alcohol", "grams", "alcohol_grams"]))
        drink_times.append(_first_present(event, ["hours_from_session_start", "time_hours", "t"]))
    return grams_by_drink, drink_times, warnings

def _extract_profile_for_implied_beta(payload: dict[str, Any]) -> tuple[Any, Any]:
    profile = payload.get("profile_snapshot")
    if not isinstance(profile, dict):
        profile = {}
    return (
        profile.get("weight_kg", payload.get("weight_kg")),
        profile.get("r", payload.get("r")),
    )

def _extract_review_for_implied_beta(payload: dict[str, Any]) -> dict[str, Any]:
    review = payload.get("review")
    if not isinstance(review, dict):
        review = {}
    return {
        "felt_sober_hours": review.get("felt_sober_hours", payload.get("felt_sober_hours")),
        "food_intake": review.get("food_intake", payload.get("food_intake", "none")),
        "final_bac_anchor": review.get("final_bac_anchor", payload.get("final_bac_anchor", 0.02)),
        "blackout": review.get("blackout", payload.get("blackout", False)),
        "vomited": review.get("vomited", payload.get("vomited", False)),
    }


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
        "body_fat_percent": number,                     // preferred, backend bucketed
        "body_fat_bracket": "low" | "mid" | "high",   // legacy fallback
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

    fat_bracket = derive_body_fat_bracket(profile)

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

    # ── r estimation (distribution/body-water coefficient) ────────────────
    # Sex selects the formula branch. Body-fat percent is noisy user-entered
    # data, so the backend converts it into broad universal buckets for r.
    r = r_coefficient(
        gender=str(sex),
        age=age,
        weight=weight,
        height=height,
        fat=fat_bracket,
    )

    # ── beta estimation (demographic prior + Bayesian personalization) ─────
    # Beta models elimination rate. It intentionally uses age, BMI,
    # drinks/week, and usable implied-beta history, not sex or body fat.
    demographic_population_beta = population_beta_prior(
        age=age,
        weight_kg=weight,
        height_cm=height,
        drinks_per_week=dpw,
    )
    observed_betas, api_excluded, beta_warnings = _extract_beta_history(history)
    beta_result = estimate_personalized_beta(
        observed_betas=observed_betas,
        population_beta=demographic_population_beta,
        min_beta=MIN_BETA_PER_HOUR,
        max_beta=MAX_BETA_PER_HOUR,
    )
    beta_per_hour = float(beta_result["beta"])
    beta_metadata = _beta_metadata_response(beta_result, api_excluded, beta_warnings)

    # ── BAC range + backend-owned curve ───────────────────────────────────
    food_intake = session.get("food_intake", payload.get("food_intake", "none"))
    drink_events = session.get("drink_events")
    curve_result: dict[str, Any] | None = None
    if isinstance(drink_events, list) and drink_events:
        curve_result = generate_event_aware_bac_curve(
            drink_events=drink_events,
            weight_kg=weight,
            r=r,
            beta_per_hour=beta_per_hour,
            food_intake=food_intake,
            current_time_hours=hours_elapsed,
        )

    if curve_result and curve_result["metadata"]["source"] == "event_aware" and curve_result["current_bac"]:
        bac = curve_result["current_bac"]
    else:
        bac = calculate_bac_range(
            alc_g=grams_alcohol,
            weight_kg=weight,
            r=r,
            beta_per_hour=beta_per_hour,
            hours_elapsed=hours_elapsed,
        )
        legacy_curve_result = generate_legacy_bac_curve(
            alc_g=grams_alcohol,
            weight_kg=weight,
            r=r,
            beta_per_hour=beta_per_hour,
            current_time_hours=hours_elapsed,
        )
        if curve_result:
            legacy_meta = legacy_curve_result["metadata"]
            event_meta = curve_result["metadata"]
            legacy_meta["ignored_drink_events"] = event_meta.get("ignored_drink_events", 0)
            legacy_meta["warnings"] = event_meta.get("warnings", []) + [
                "falling_back_to_legacy_total_grams_curve"
            ]
        curve_result = legacy_curve_result

    # ── personalization metadata ──────────────────────────────────────────
    n_sessions          = int(beta_metadata["sessions_used"])
    prior_weight_pct    = round(beta_metadata["population_weight"] * 100, 1)
    personal_weight_pct = round(beta_metadata["personal_weight"] * 100, 1)
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
            "body_fat_bracket":    fat_bracket,
            "beta_per_hour":       round(beta_per_hour, 6),
            "beta_source":         beta_metadata["source"],
            "coefficient_source":  COEFFICIENT_SOURCE,
            "personalization":     personalization_status,
            "sessions_used":       n_sessions,
            "sessions_excluded":   beta_metadata["sessions_excluded"],
            "prior_weight_pct":    prior_weight_pct,
            "personal_weight_pct": personal_weight_pct,
        },
        "beta_metadata": beta_metadata,
        "bac": {
            "low":      round(float(bac["low"]),      6),
            "current":  round(float(bac["estimate"]), 6),
            "estimate": round(float(bac["estimate"]), 6),
            "high":     round(float(bac["high"]),     6),
        },
        "current_bac": round(float(bac["estimate"]), 6),
        "peak_bac": None if not curve_result or curve_result.get("peak_bac") is None else round(float(curve_result["peak_bac"]), 6),
        "peak_bac_hour": None if not curve_result or curve_result.get("peak_bac_hour") is None else round(float(curve_result["peak_bac_hour"]), 4),
        "peak_status": None if not curve_result else curve_result.get("peak_status"),
        "time_to_peak_hours": None if not curve_result or curve_result.get("time_to_peak_hours") is None else round(float(curve_result["time_to_peak_hours"]), 4),
        "curve": curve_result["curve"] if curve_result else [],
        "curve_metadata": curve_result["metadata"] if curve_result else {
            "source": "unavailable",
            "model": "none",
            "food_intake": "none",
            "step_minutes": None,
            "valid_drink_events": 0,
            "ignored_drink_events": 0,
            "warnings": ["curve_generation_unavailable"],
        },
        "estimated_near_zero_hour": (
            None if not curve_result else curve_result.get("estimated_near_zero_hour")
        ),
        "meta": {
            "disclaimer": (
                "Estimate only; not legal or medical advice. "
                "Do not use this estimate to make driving decisions."
            )
        },
    }


def implied_beta_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Compute event-aware session-implied beta metadata after review."""
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    grams_by_drink, drink_times, warnings = _extract_drink_events_for_implied_beta(payload)
    weight_kg, r = _extract_profile_for_implied_beta(payload)
    review = _extract_review_for_implied_beta(payload)
    result = estimate_implied_beta_from_session(
        grams_by_drink=grams_by_drink,
        drink_times_hours=drink_times,
        felt_sober_hours=review["felt_sober_hours"],
        food_intake=review["food_intake"],
        weight_kg=weight_kg,
        r=r,
        prior_beta=payload.get("prior_beta", 0.015),
        final_bac_anchor=review["final_bac_anchor"],
        blackout=review["blackout"] is True,
        vomited=review["vomited"] is True,
    )

    validity_flags = result.setdefault("validity_flags", [])
    for warning in warnings:
        if warning not in validity_flags:
            validity_flags.append(warning)
    result["warnings"] = warnings
    result["instructions"] = (
        "Store this result with the reviewed session. Include implied_beta in "
        "future /predict history only when usable_for_personalization is true."
    )
    return result


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
