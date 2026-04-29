"""Event-aware reverse-beta estimation helpers.

The functions in this module back-calculate one session-implied alcohol
elimination rate from drink events and a post-session review. Beta is measured
in BAC display units per hour: ``0.015`` means estimated BAC declines by about
0.015 per hour. The result is heuristic personalization metadata, not a medical
measurement.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


DEFAULT_BETA = 0.015
DEFAULT_FINAL_BAC_ANCHOR = 0.02
DEFAULT_MIN_BETA = 0.005
DEFAULT_MAX_BETA = 0.030
NEAR_ZERO_BAC = 0.003
METHOD_NAME = "event_aware_absorption_reverse_beta_v1"

FOOD_PEAK_HOURS = {
    "none": 0.25,
    "low": 0.50,
    "medium": 1.25,
    "high": 1.50,
}

SEVERE_FLAGS = {
    "missing_drink_events",
    "mismatched_drink_grams_and_times",
    "invalid_drink_grams",
    "invalid_drink_times",
    "invalid_weight_kg",
    "invalid_r",
    "missing_felt_sober_hours",
    "invalid_felt_sober_hours",
    "felt_sober_not_after_effective_start",
    "final_bac_anchor_not_below_estimated_peak",
    "nonpositive_raw_implied_beta",
    "vomiting_reported_unreliable_for_personalization",
}


def _coerce_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _sanitize_beta_bounds(min_beta: Any, max_beta: Any, flags: list[str]) -> tuple[float, float]:
    min_value = _coerce_finite_float(min_beta)
    max_value = _coerce_finite_float(max_beta)
    if min_value is None or max_value is None or min_value <= 0 or max_value <= min_value:
        flags.append("invalid_beta_bounds_defaulted")
        return DEFAULT_MIN_BETA, DEFAULT_MAX_BETA
    return min_value, max_value


def _result_template(
    *,
    flags: list[str],
    food_intake: str,
    final_bac_anchor: float,
    felt_sober_hours: float | None,
    blackout: bool,
    vomited: bool,
) -> dict[str, Any]:
    return {
        "implied_beta": None,
        "raw_implied_beta": None,
        "usable_for_personalization": False,
        "confidence": 0.0,
        "validity_flags": flags,
        "method": METHOD_NAME,
        "units": {
            "beta": "bac_percent_points_per_hour",
            "bac": "percent_bac_display_decimal",
            "alcohol": "grams",
            "weight": "kg",
            "time": "hours",
        },
        "effective_start_time": None,
        "effective_drink_count": 0,
        "effective_grams": 0.0,
        "estimated_peak_bac": None,
        "final_bac_anchor": final_bac_anchor,
        "felt_sober_hours": felt_sober_hours,
        "food_intake": food_intake,
        "blackout": bool(blackout),
        "vomited": bool(vomited),
    }


def normalize_food_intake(food_intake: Any) -> str:
    """Normalize food intake labels to none/low/medium/high."""
    if food_intake is None:
        return "none"
    value = str(food_intake).strip().lower()
    if value in {"", "none", "no", "no food"}:
        return "none"
    if value == "low":
        return "low"
    if value in {"medium", "mid"}:
        return "medium"
    if value == "high":
        return "high"
    return "none"


def _normalize_food_with_flag(food_intake: Any) -> tuple[str, bool]:
    if food_intake is None:
        return "none", False
    value = str(food_intake).strip().lower()
    known = value in {"", "none", "no", "no food", "low", "medium", "mid", "high"}
    return normalize_food_intake(food_intake), not known


def absorption_peak_hours(food_intake: Any) -> float:
    """Return the assumed time to near-full absorption for the food bracket."""
    return FOOD_PEAK_HOURS[normalize_food_intake(food_intake)]


def absorbed_grams(
    food_intake: Any,
    grams_alcohol: float,
    intake_time_hours: float,
    current_time_hours: float,
) -> float:
    """Estimate grams absorbed into the body by ``current_time_hours``.

    This returns absorbed alcohol, not alcohol remaining after elimination. A
    smoothstep curve gives a gradual rise between drink time and food-adjusted
    peak absorption.
    """
    grams = _coerce_finite_float(grams_alcohol)
    intake_time = _coerce_finite_float(intake_time_hours)
    current_time = _coerce_finite_float(current_time_hours)
    if grams is None or grams <= 0 or intake_time is None or current_time is None:
        return 0.0
    if current_time <= intake_time:
        return 0.0

    peak_time = absorption_peak_hours(food_intake)
    elapsed = current_time - intake_time
    if elapsed >= peak_time:
        return grams

    progress = _clamp(elapsed / peak_time, 0.0, 1.0)
    smooth_progress = progress * progress * (3.0 - 2.0 * progress)
    return grams * smooth_progress


def bac_from_grams(grams_alcohol: float, weight_kg: float, r: float) -> float:
    """Convert grams ethanol to display BAC where 0.08 means 0.08% BAC."""
    grams = _coerce_finite_float(grams_alcohol)
    weight = _coerce_finite_float(weight_kg)
    r_value = _coerce_finite_float(r)
    if grams is None or grams < 0:
        raise ValueError("grams_alcohol must be a finite nonnegative number.")
    if weight is None or weight <= 0:
        raise ValueError("weight_kg must be a finite positive number.")
    if r_value is None or r_value <= 0:
        raise ValueError("r must be a finite positive number.")
    return grams / (weight * 10.0 * r_value)


def _as_event_lists(
    grams_by_drink: Iterable[Any] | None,
    drink_times_hours: Iterable[Any] | None,
) -> tuple[list[tuple[float, float]], list[str]]:
    flags: list[str] = []
    if grams_by_drink is None or drink_times_hours is None:
        return [], ["missing_drink_events"]
    if isinstance(grams_by_drink, (str, bytes)) or isinstance(drink_times_hours, (str, bytes)):
        return [], ["invalid_drink_events_type"]

    try:
        grams_raw = list(grams_by_drink)
        times_raw = list(drink_times_hours)
    except TypeError:
        return [], ["invalid_drink_events_type"]

    if not grams_raw or not times_raw:
        return [], ["missing_drink_events"]
    if len(grams_raw) != len(times_raw):
        return [], ["mismatched_drink_grams_and_times"]

    events: list[tuple[float, float]] = []
    for raw_grams, raw_time in zip(grams_raw, times_raw):
        grams = _coerce_finite_float(raw_grams)
        drink_time = _coerce_finite_float(raw_time)
        if grams is None or grams <= 0:
            flags.append("invalid_drink_grams")
        if drink_time is None or drink_time < 0:
            flags.append("invalid_drink_times")
        if grams is not None and grams > 0 and drink_time is not None and drink_time >= 0:
            events.append((drink_time, grams))

    if flags:
        return [], sorted(set(flags))

    sorted_events = sorted(events, key=lambda item: item[0])
    if sorted_events != events:
        flags.append("drink_events_sorted_by_time")
    return sorted_events, flags


def maybe_effective_session_start(
    events: list[tuple[float, float]],
    food_intake: str,
    weight_kg: float,
    r: float,
    prior_beta: float = DEFAULT_BETA,
    near_zero_bac: float = NEAR_ZERO_BAC,
) -> tuple[int, float | None, list[str]]:
    """Estimate whether earlier drinks likely cleared before a later drink."""
    flags: list[str] = []
    if not events:
        return 0, None, flags

    reset_index = 0
    for next_index in range(1, len(events)):
        next_time = events[next_index][0]
        effective_start_time = events[reset_index][0]
        absorbed = sum(
            absorbed_grams(food_intake, grams, drink_time, next_time)
            for drink_time, grams in events[reset_index:next_index]
        )
        bac_before_next = max(
            0.0,
            bac_from_grams(absorbed, weight_kg, r) - prior_beta * (next_time - effective_start_time),
        )
        if bac_before_next <= near_zero_bac:
            reset_index = next_index
            flags.append("effective_start_reset_after_likely_zero_bac")

    return reset_index, events[reset_index][0], sorted(set(flags))


def _confidence_from_flags(flags: list[str]) -> float:
    confidence = 1.0
    if "effective_start_reset_after_likely_zero_bac" in flags:
        confidence -= 0.2
    if "raw_implied_beta_outside_plausible_range_clipped" in flags:
        confidence -= 0.3
    if "blackout_reported_reduces_confidence" in flags:
        confidence -= 0.5
    if "vomiting_reported_unreliable_for_personalization" in flags:
        confidence -= 0.8
    if "unknown_food_intake_defaulted_to_none" in flags:
        confidence -= 0.2
    return _clamp(confidence, 0.0, 1.0)


def _has_severe_flags(flags: list[str]) -> bool:
    return any(flag in SEVERE_FLAGS for flag in flags)


def estimate_implied_beta_from_session(
    grams_by_drink: Iterable[Any] | None,
    drink_times_hours: Iterable[Any] | None,
    felt_sober_hours: float | None = None,
    food_intake: Any = "none",
    weight_kg: float | None = None,
    r: float | None = None,
    prior_beta: float = DEFAULT_BETA,
    final_bac_anchor: float = DEFAULT_FINAL_BAC_ANCHOR,
    blackout: bool = False,
    vomited: bool = False,
    min_beta: float = DEFAULT_MIN_BETA,
    max_beta: float = DEFAULT_MAX_BETA,
) -> dict[str, Any]:
    """Estimate one session-implied beta from event-level review data."""
    flags: list[str] = []
    food, unknown_food = _normalize_food_with_flag(food_intake)
    if unknown_food:
        flags.append("unknown_food_intake_defaulted_to_none")

    min_beta, max_beta = _sanitize_beta_bounds(min_beta, max_beta, flags)
    prior_beta_value = _coerce_finite_float(prior_beta)
    if prior_beta_value is None or prior_beta_value <= 0:
        flags.append("invalid_prior_beta_defaulted")
        prior_beta_value = DEFAULT_BETA

    final_anchor = _coerce_finite_float(final_bac_anchor)
    if final_anchor is None or final_anchor < 0:
        flags.append("invalid_final_bac_anchor_defaulted")
        final_anchor = DEFAULT_FINAL_BAC_ANCHOR

    felt_sober_value = None if felt_sober_hours is None else _coerce_finite_float(felt_sober_hours)
    result = _result_template(
        flags=flags,
        food_intake=food,
        final_bac_anchor=final_anchor,
        felt_sober_hours=felt_sober_value,
        blackout=blackout,
        vomited=vomited,
    )

    if blackout:
        flags.append("blackout_reported_reduces_confidence")
    if vomited:
        flags.append("vomiting_reported_unreliable_for_personalization")

    weight = _coerce_finite_float(weight_kg)
    if weight is None or weight <= 0:
        flags.append("invalid_weight_kg")
        return result

    r_value = _coerce_finite_float(r)
    if r_value is None or r_value <= 0:
        flags.append("invalid_r")
        return result

    events, event_flags = _as_event_lists(grams_by_drink, drink_times_hours)
    flags.extend(event_flags)
    if event_flags and not events:
        return result

    reset_index, effective_start_time, reset_flags = maybe_effective_session_start(
        events=events,
        food_intake=food,
        weight_kg=weight,
        r=r_value,
        prior_beta=prior_beta_value,
    )
    flags.extend(flag for flag in reset_flags if flag not in flags)

    effective_events = events[reset_index:]
    effective_grams = sum(grams for _, grams in effective_events)
    estimated_peak_bac = bac_from_grams(effective_grams, weight, r_value)

    result.update({
        "validity_flags": flags,
        "effective_start_time": effective_start_time,
        "effective_drink_count": len(effective_events),
        "effective_grams": effective_grams,
        "estimated_peak_bac": estimated_peak_bac,
    })

    if felt_sober_hours is None:
        flags.append("missing_felt_sober_hours")
        if blackout:
            flags.append("blackout_without_felt_sober_cannot_estimate_beta")
        result["validity_flags"] = flags
        return result

    if felt_sober_value is None or felt_sober_value <= 0:
        flags.append("invalid_felt_sober_hours")
        result["validity_flags"] = flags
        return result

    if effective_start_time is None or felt_sober_value <= effective_start_time:
        flags.append("felt_sober_not_after_effective_start")
        result["validity_flags"] = flags
        return result

    elapsed_hours = felt_sober_value - effective_start_time
    if final_anchor >= estimated_peak_bac:
        flags.append("final_bac_anchor_not_below_estimated_peak")
        result["validity_flags"] = flags
        return result

    raw_implied_beta = (estimated_peak_bac - final_anchor) / elapsed_hours
    if raw_implied_beta <= 0:
        flags.append("nonpositive_raw_implied_beta")
        result["raw_implied_beta"] = raw_implied_beta
        result["validity_flags"] = flags
        return result

    implied_beta = raw_implied_beta
    if implied_beta < min_beta or implied_beta > max_beta:
        flags.append("raw_implied_beta_outside_plausible_range_clipped")
        implied_beta = _clamp(implied_beta, min_beta, max_beta)

    confidence = _confidence_from_flags(flags)
    usable = implied_beta is not None and confidence >= 0.5 and not _has_severe_flags(flags)

    result.update({
        "implied_beta": implied_beta,
        "raw_implied_beta": raw_implied_beta,
        "usable_for_personalization": usable,
        "confidence": confidence,
        "validity_flags": flags,
    })
    return result


def BACCalculator(alc_g: float, weight: float, r: float, beta: float, time: float) -> float:
    """Compatibility wrapper using the corrected display-BAC formula."""
    return bac_from_grams(alc_g, weight, r) - float(beta) * float(time)


def absorbtion(food: Any, grams_alc: float, intake_time: float, time: float) -> float:
    """Compatibility wrapper for the prototype's misspelled function name."""
    return absorbed_grams(food, grams_alc, intake_time, time)


__all__ = [
    "BACCalculator",
    "absorbtion",
    "absorbed_grams",
    "absorption_peak_hours",
    "bac_from_grams",
    "estimate_implied_beta_from_session",
    "maybe_effective_session_start",
    "normalize_food_intake",
]
