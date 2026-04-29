"""Deterministic + Bayesian BAC helper functions for a Widmark-style scaffold.

Unit contract used throughout this module:
- alcohol input: grams ethanol
- weight input: kilograms
- height input: centimeters
- time input: hours
- BAC output: display-scale decimal (0.08 means 0.08% BAC)
- beta: BAC units per hour (0.015 BAC/hour)
- r: dimensionless distribution ratio

Modeling approach:
- r is estimated via linear regression on sex, age, weight, height, body fat bracket
  (coefficients derived from NHANES body composition data; see AGENTS.md)
- beta uses a Bayesian shrinkage estimator: population prior (mean=0.015, sd=0.0025)
  updated with session-implied betas from post-session review data.
  As sessions accumulate, personal history progressively dominates population prior.
- BAC range uses conservative perturbation of r and beta to bound uncertainty.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


# ── Population-level constants ─────────────────────────────────────────────
DEFAULT_BETA_PER_HOUR = 0.015   # literature population mean elimination rate
DEFAULT_BETA_SD       = 0.0025  # population SD for beta (Widmark / JSAD sources)
MIN_R                 = 0.45
MAX_R                 = 0.80
MIN_BETA_PER_HOUR     = 0.005
MAX_BETA_PER_HOUR     = 0.030

# Bayesian shrinkage prior weight.
# Equivalent to "how many sessions worth of data does the population prior represent."
# At 10 sessions of personal data, personal history = 50% of the estimate.
PRIOR_SESSION_WEIGHT  = 10.0

# ── r regression coefficients (NHANES-derived linear model) ───────────────
# Predicts Widmark r from: intercept, age, weight(kg), height(cm), fat bracket
# Fat bracket: low / mid add a positive bump; high (default) adds nothing.
m_i      = 0.3901319484;  m_age    = 0.0003273190;  m_weight = -0.0009810014
m_height = 0.0011555900;  m_low    = 0.1173256496;  m_mid    = 0.0633215674

f_i      = 0.3945319640;  f_age    = 0.0001213782;  f_weight = -0.0014620109
f_height = 0.0009572304;  f_low    = 0.1155135171;  f_mid    = 0.0605819172

n_i      = 0.2181713778;  n_age    = -0.0002123286; n_weight = -0.0011931574
n_height = 0.0021444658;  n_low    = 0.1388081199;  n_mid    = 0.0756061038

# ── Beta age-band modifiers (literature-backed blocking) ──────────────────
# Source: JSAD 1985, PMC6761697, PMC11265204
# Age bands are intentionally broad (10yr) to avoid overfitting.
# Values are additive adjustments relative to DEFAULT_BETA_PER_HOUR.
BETA_AGE_BAND_OFFSETS: dict[tuple[int, int], float] = {
    (18, 25): -0.0010,   # younger: slightly slower metabolism
    (26, 35):  0.0000,   # reference band
    (36, 50):  0.0010,   # moderate increase with age
    (51, 65):  0.0015,   # older adults: faster AER per literature
    (66, 120): 0.0020,   # elderly: fastest AER
}

# BMI modifiers: obesity and higher lean mass associated with faster AER (PMC11265204)
BETA_BMI_OFFSETS: list[tuple[float, float, float]] = [
    (0,    18.5, -0.0015),   # underweight
    (18.5, 25.0,  0.0000),   # normal (reference)
    (25.0, 30.0,  0.0005),   # overweight
    (30.0, 999,   0.0020),   # obese: 52% faster AER per PMC11265204
]

# Drinks-per-week modifier: chronic drinking upregulates alcohol dehydrogenase
BETA_DRINKS_PER_WEEK_OFFSETS: list[tuple[float, float, float]] = [
    (0,   7,   0.0000),
    (7,   14,  0.0005),
    (14,  21,  0.0010),
    (21,  999, 0.0015),
]


# ── Utility ───────────────────────────────────────────────────────────────

def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))

def validate_positive_number(value: float, name: str) -> None:
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number.")

def validate_nonnegative_number(value: float, name: str) -> None:
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a nonnegative number.")

def _normalize_gender(gender: str | None) -> str:
    if gender is None:
        return "neutral"
    g = str(gender).strip().lower()
    if g in {"m", "male"}:   return "male"
    if g in {"f", "female"}: return "female"
    return "neutral"

def _normalize_fat_level(fat: str | None) -> str:
    if fat is None: return "high"
    normalized = str(fat).strip().lower()
    if normalized == "low":             return "low"
    if normalized in {"mid", "medium"}: return "mid"
    return "high"


# ── r estimation (regression) ─────────────────────────────────────────────

def r_coefficient(
    gender: str | None,
    age: float,
    weight: float,
    height: float,
    fat: str | None = None,
) -> float:
    """Estimate Widmark r via linear regression on demographics.

    Args:
        gender: 'm'/'male', 'f'/'female', or any other value → neutral model.
        age:    Years. Must be positive.
        weight: Kilograms. Must be positive.
        height: Centimeters. Must be positive.
        fat:    Body fat bracket — 'low', 'mid'/'medium', 'high', or None.

    Returns:
        r clamped to [MIN_R, MAX_R].
    """
    validate_positive_number(age,    "age")
    validate_positive_number(weight, "weight")
    validate_positive_number(height, "height")

    g         = _normalize_gender(gender)
    fat_level = _normalize_fat_level(fat)

    if g == "male":
        r_val = m_i + m_age * age + m_weight * weight + m_height * height
        if fat_level == "low": r_val += m_low
        elif fat_level == "mid": r_val += m_mid
    elif g == "female":
        r_val = f_i + f_age * age + f_weight * weight + f_height * height
        if fat_level == "low": r_val += f_low
        elif fat_level == "mid": r_val += f_mid
    else:
        r_val = n_i + n_age * age + n_weight * weight + n_height * height
        if fat_level == "low": r_val += n_low
        elif fat_level == "mid": r_val += n_mid

    return clamp(r_val, MIN_R, MAX_R)


# ── beta estimation (population prior + Bayesian shrinkage) ───────────────

def _beta_age_band_offset(age: float) -> float:
    """Return the additive beta offset for the user's age band."""
    for (lo, hi), offset in BETA_AGE_BAND_OFFSETS.items():
        if lo <= age <= hi:
            return offset
    return 0.0

def _beta_bmi_offset(weight_kg: float, height_cm: float) -> float:
    """Return the additive beta offset for the user's BMI bracket."""
    if height_cm <= 0:
        return 0.0
    bmi = weight_kg / ((height_cm / 100.0) ** 2)
    for lo, hi, offset in BETA_BMI_OFFSETS:
        if lo <= bmi < hi:
            return offset
    return 0.0

def _beta_drinks_per_week_offset(drinks_per_week: float) -> float:
    """Return the additive beta offset for habitual drinking frequency."""
    for lo, hi, offset in BETA_DRINKS_PER_WEEK_OFFSETS:
        if lo <= drinks_per_week < hi:
            return offset
    return 0.0

def population_beta_prior(
    age: float = 25.0,
    weight_kg: float = 70.0,
    height_cm: float = 170.0,
    drinks_per_week: float = 0.0,
) -> float:
    """Compute the demographic-adjusted population prior for beta.

    Applies literature-backed age-band, BMI, and drinking-frequency offsets
    to the population mean. This is the starting estimate for a new user
    before any personal session data exists.

    Returns:
        Beta clamped to [MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR].
    """
    prior = (
        DEFAULT_BETA_PER_HOUR
        + _beta_age_band_offset(age)
        + _beta_bmi_offset(weight_kg, height_cm)
        + _beta_drinks_per_week_offset(drinks_per_week)
    )
    return clamp(prior, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)


def implied_beta_from_session(
    grams_alcohol: float,
    weight_kg: float,
    r: float,
    felt_sober_hours: float,
) -> float | None:
    """Legacy single-drink implied-beta wrapper.

    New event-aware API code should call reversebeta.estimate_implied_beta_from_session().
    This wrapper preserves the old behavior by treating the session as one drink
    at t=0 and using a 0.0 final BAC anchor.

    Returns:
        Implied beta clamped to valid range, or None if inputs are invalid.
    """
    from reversebeta import estimate_implied_beta_from_session

    result = estimate_implied_beta_from_session(
        grams_by_drink=[grams_alcohol],
        drink_times_hours=[0.0],
        felt_sober_hours=felt_sober_hours,
        weight_kg=weight_kg,
        r=r,
        final_bac_anchor=0.0,
        min_beta=MIN_BETA_PER_HOUR,
        max_beta=MAX_BETA_PER_HOUR,
    )
    implied = result.get("implied_beta")
    if implied is None:
        return None
    return float(implied)


def personalize_beta(
    prior_beta: float = DEFAULT_BETA_PER_HOUR,
    session_implied_betas: list[float] | None = None,
    prior_weight: float = PRIOR_SESSION_WEIGHT,
) -> float:
    """Backward-compatible wrapper around BayesianStats personalization.

    Args:
        prior_beta:            Population or demographic prior for this user.
        session_implied_betas: List of back-calculated betas from past sessions.
        prior_weight:          Deprecated; retained for call compatibility.

    Returns:
        Personalized beta clamped to [MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR].
    """
    validate_positive_number(prior_beta, "prior_beta")
    validate_positive_number(prior_weight, "prior_weight")

    from BayesianStats import estimate_personalized_beta

    result = estimate_personalized_beta(
        observed_betas=session_implied_betas or [],
        population_beta=prior_beta,
        prior_sd=DEFAULT_BETA_SD,
        min_beta=MIN_BETA_PER_HOUR,
        max_beta=MAX_BETA_PER_HOUR,
    )
    return float(result["beta"])


def estimate_beta(
    profile: dict | None = None,
    session_history: Iterable[float] | None = None,
) -> float:
    """Return the best available beta estimate for a user.

    - With no profile and no history → population default (0.015).
    - With profile only → demographic-adjusted prior.
    - With history → Bayesian shrinkage of demographic prior toward personal betas.

    Args:
        profile: Dict with optional keys: age, weight_kg, height_cm, drinks_per_week.
        session_history: Iterable of session-implied beta values from past reviews.

    Returns:
        Beta clamped to [MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR].
    """
    if profile is None:
        profile = {}

    prior = population_beta_prior(
        age             = float(profile.get("age",              25.0)),
        weight_kg       = float(profile.get("weight_kg",        70.0)),
        height_cm       = float(profile.get("height_cm",       170.0)),
        drinks_per_week = float(profile.get("drinks_per_week",   0.0)),
    )

    history_list = list(session_history) if session_history is not None else []

    return personalize_beta(
        prior_beta            = prior,
        session_implied_betas = history_list,
        prior_weight          = PRIOR_SESSION_WEIGHT,
    )


# ── Core BAC calculation ───────────────────────────────────────────────────

def calculate_bac(
    alc_g: float,
    weight_kg: float,
    r: float,
    beta_per_hour: float = DEFAULT_BETA_PER_HOUR,
    hours_elapsed: float = 0.0,
) -> float:
    """Calculate BAC using Widmark-style mass balance.

    Formula: BAC = A / (W_kg * 10 * r) - beta * t

    The factor of 10 converts kg body weight to the dL body-water volume term,
    producing the correct display-scale g/dL result (0.08 = 0.08% BAC).

    Returns:
        BAC display decimal, floored at 0.0.
    """
    validate_nonnegative_number(alc_g,        "alc_g")
    validate_positive_number(weight_kg,        "weight_kg")
    validate_positive_number(r,                "r")
    validate_nonnegative_number(beta_per_hour, "beta_per_hour")
    validate_nonnegative_number(hours_elapsed, "hours_elapsed")

    r_clamped    = clamp(r,            MIN_R,            MAX_R)
    beta_clamped = clamp(beta_per_hour, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)

    raw_bac     = alc_g / (weight_kg * 10.0 * r_clamped)
    current_bac = raw_bac - beta_clamped * hours_elapsed
    return max(current_bac, 0.0)


def calculate_bac_range(
    alc_g: float,
    weight_kg: float,
    r: float,
    beta_per_hour: float = DEFAULT_BETA_PER_HOUR,
    hours_elapsed: float = 0.0,
    r_margin: float      = 0.05,
    beta_margin: float   = DEFAULT_BETA_SD,
) -> dict:
    """Return a low/estimate/high BAC range via conservative perturbation.

    - low:      optimistic dispersion and faster elimination (higher r, higher beta)
    - estimate: central estimate using provided r and beta
    - high:     conservative dispersion and slower elimination (lower r, lower beta)

    The margin defaults use DEFAULT_BETA_SD (0.0025) which reflects the
    population SD from the Widmark / JSAD literature.
    """
    validate_nonnegative_number(r_margin,    "r_margin")
    validate_nonnegative_number(beta_margin, "beta_margin")

    estimate = calculate_bac(alc_g, weight_kg, r, beta_per_hour, hours_elapsed)

    low = calculate_bac(
        alc_g, weight_kg,
        clamp(r + r_margin, MIN_R, MAX_R),
        clamp(beta_per_hour + beta_margin, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR),
        hours_elapsed,
    )
    high = calculate_bac(
        alc_g, weight_kg,
        clamp(r - r_margin, MIN_R, MAX_R),
        clamp(beta_per_hour - beta_margin, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR),
        hours_elapsed,
    )

    ordered = sorted([low, estimate, high])
    return {
        "low":      max(ordered[0], 0.0),
        "estimate": max(ordered[1], 0.0),
        "high":     max(ordered[2], 0.0),
    }


# ── Event-aware BAC curve calculation ─────────────────────────────────────

EVENT_CURVE_MODEL = "per_drink_absorption_with_independent_elimination_approximation"
DEFAULT_CURVE_STEP_MINUTES = 10
NEAR_ZERO_BAC_THRESHOLD = 0.003


def _coerce_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_present(mapping: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in mapping:
            return mapping.get(name)
    return None


def normalize_drink_events(drink_events: Iterable[Any] | None) -> tuple[list[dict[str, float]], int, list[str]]:
    """Normalize event-level drink input for BAC prediction.

    Returns:
        ``(events, ignored_count, warnings)`` where each event has
        ``grams_alcohol`` and ``hours_from_session_start``. Invalid events are
        ignored so old or partially corrupt frontend storage cannot crash a
        prediction request.
    """
    warnings: list[str] = []
    if drink_events is None:
        return [], 0, warnings
    if isinstance(drink_events, (str, bytes)):
        return [], 1, ["drink_events_not_list"]

    try:
        raw_events = list(drink_events)
    except TypeError:
        return [], 1, ["drink_events_not_list"]

    events: list[dict[str, float]] = []
    ignored = 0
    for raw in raw_events:
        if not isinstance(raw, dict):
            ignored += 1
            continue
        grams = _coerce_finite_float(_first_present(raw, ["grams_alcohol", "grams", "alcohol_grams"]))
        hour = _coerce_finite_float(_first_present(raw, ["hours_from_session_start", "time_hours", "t"]))
        if grams is None or grams <= 0 or hour is None or hour < 0:
            ignored += 1
            continue
        events.append({
            "grams_alcohol": grams,
            "hours_from_session_start": hour,
        })

    if ignored:
        warnings.append("invalid_drink_events_ignored")

    sorted_events = sorted(events, key=lambda event: event["hours_from_session_start"])
    if sorted_events != events:
        warnings.append("drink_events_sorted_by_time")
    return sorted_events, ignored, warnings


def absorbed_alcohol_at_time(
    drink_events: Iterable[Any] | None,
    t: float,
    food_intake: str = "none",
) -> float:
    """Return total grams absorbed by time ``t`` from normalized/raw events."""
    from reversebeta import absorbed_grams

    time = _coerce_finite_float(t)
    if time is None:
        return 0.0
    events, _, _ = normalize_drink_events(drink_events)
    return sum(
        absorbed_grams(
            food_intake,
            event["grams_alcohol"],
            event["hours_from_session_start"],
            time,
        )
        for event in events
    )


def event_aware_bac_at_time(
    drink_events: Iterable[Any] | None,
    t: float,
    weight_kg: float,
    r: float,
    beta_per_hour: float,
    food_intake: str = "none",
) -> float:
    """Estimate BAC at time ``t`` using drink timing and absorption.

    This is an explainable approximation for product estimation: each drink is
    absorbed with the shared food-adjusted absorption curve, converted into BAC
    display units, then reduced by beta from that drink's event time. Real
    elimination acts on total body alcohol rather than independent drinks, so
    response metadata names this approximation explicitly.
    """
    from reversebeta import absorbed_grams, bac_from_grams

    time = _coerce_finite_float(t)
    validate_positive_number(weight_kg, "weight_kg")
    validate_positive_number(r, "r")
    validate_nonnegative_number(beta_per_hour, "beta_per_hour")
    if time is None or time < 0:
        raise ValueError("t must be a finite nonnegative number.")

    r_clamped = clamp(r, MIN_R, MAX_R)
    beta_clamped = clamp(beta_per_hour, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)
    events, _, _ = normalize_drink_events(drink_events)
    total_bac = 0.0

    for event in events:
        drink_time = event["hours_from_session_start"]
        absorbed = absorbed_grams(food_intake, event["grams_alcohol"], drink_time, time)
        if absorbed <= 0:
            continue
        contribution_bac = bac_from_grams(absorbed, weight_kg, r_clamped)
        eliminated_bac = beta_clamped * max(0.0, time - drink_time)
        total_bac += max(0.0, contribution_bac - eliminated_bac)

    return max(total_bac, 0.0)


def calculate_event_aware_bac_range(
    drink_events: Iterable[Any] | None,
    weight_kg: float,
    r: float,
    beta_per_hour: float,
    hours_elapsed: float,
    food_intake: str = "none",
    r_margin: float = 0.05,
    beta_margin: float = DEFAULT_BETA_SD,
) -> dict[str, float]:
    """Return low/estimate/high BAC range using event-aware timing."""
    estimate = event_aware_bac_at_time(
        drink_events, hours_elapsed, weight_kg, r, beta_per_hour, food_intake
    )
    low = event_aware_bac_at_time(
        drink_events,
        hours_elapsed,
        weight_kg,
        clamp(r + r_margin, MIN_R, MAX_R),
        clamp(beta_per_hour + beta_margin, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR),
        food_intake,
    )
    high = event_aware_bac_at_time(
        drink_events,
        hours_elapsed,
        weight_kg,
        clamp(r - r_margin, MIN_R, MAX_R),
        clamp(beta_per_hour - beta_margin, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR),
        food_intake,
    )
    ordered = sorted([low, estimate, high])
    return {
        "low": max(ordered[0], 0.0),
        "estimate": max(ordered[1], 0.0),
        "high": max(ordered[2], 0.0),
    }


def _curve_hours(
    *,
    current_time_hours: float | None,
    last_drink_time: float,
    step_hours: float,
    horizon_hours: float | None,
) -> list[float]:
    current = current_time_hours if current_time_hours is not None else 0.0
    if horizon_hours is None:
        horizon = max(current + 4.0, last_drink_time + 8.0, 8.0)
    else:
        horizon = horizon_hours
    horizon = clamp(horizon, max(current, 0.0), 24.0)

    hours: list[float] = []
    point = 0.0
    while point <= horizon + 1e-9:
        hours.append(round(point, 4))
        point += step_hours
    for extra in (current, horizon):
        if extra is not None and extra >= 0:
            hours.append(round(extra, 4))
    return sorted(set(hours))


def generate_event_aware_bac_curve(
    drink_events: Iterable[Any] | None,
    weight_kg: float,
    r: float,
    beta_per_hour: float,
    food_intake: str = "none",
    current_time_hours: float | None = None,
    horizon_hours: float | None = None,
    step_minutes: int = DEFAULT_CURVE_STEP_MINUTES,
) -> dict[str, Any]:
    """Generate backend-owned event-aware BAC curve points.

    The curve uses display-scale BAC units and the same beta/r units as
    ``calculate_bac``. Returned metadata names the approximation so the product
    does not overstate medical precision.
    """
    from reversebeta import absorption_peak_hours, normalize_food_intake

    validate_positive_number(weight_kg, "weight_kg")
    validate_positive_number(r, "r")
    validate_nonnegative_number(beta_per_hour, "beta_per_hour")
    events, ignored, warnings = normalize_drink_events(drink_events)
    food = normalize_food_intake(food_intake)
    if not events:
        return {
            "curve": [],
            "current_bac": None,
            "estimated_near_zero_hour": None,
            "metadata": {
                "source": "legacy_total_grams",
                "model": "legacy_total_grams_all_at_start",
                "food_intake": food,
                "step_minutes": step_minutes,
                "valid_drink_events": 0,
                "ignored_drink_events": ignored,
                "warnings": warnings + ["no_valid_drink_events_for_event_curve"],
            },
        }

    step = max(1, int(step_minutes)) / 60.0
    current = _coerce_finite_float(current_time_hours)
    if current is not None and current < 0:
        current = 0.0
    last_drink_time = max(event["hours_from_session_start"] for event in events)
    near_zero_search_start = max(
        current or 0.0,
        last_drink_time + absorption_peak_hours(food),
    )
    hours = _curve_hours(
        current_time_hours=current,
        last_drink_time=last_drink_time,
        step_hours=step,
        horizon_hours=horizon_hours,
    )

    curve = []
    near_zero_hour = None
    has_positive_after_current = False
    for hour in hours:
        values = calculate_event_aware_bac_range(
            events,
            weight_kg=weight_kg,
            r=r,
            beta_per_hour=beta_per_hour,
            hours_elapsed=hour,
            food_intake=food,
        )
        estimate = values["estimate"]
        if hour >= near_zero_search_start:
            if estimate > NEAR_ZERO_BAC_THRESHOLD:
                has_positive_after_current = True
            elif has_positive_after_current and near_zero_hour is None:
                near_zero_hour = hour
        curve.append({
            "hour": round(hour, 4),
            "low": round(values["low"], 6),
            "estimate": round(estimate, 6),
            "high": round(values["high"], 6),
        })

    while near_zero_hour is None and hours[-1] < 24.0:
        next_hour = min(24.0, round(hours[-1] + max(1.0, step), 4))
        hours.append(next_hour)
        values = calculate_event_aware_bac_range(
            events,
            weight_kg=weight_kg,
            r=r,
            beta_per_hour=beta_per_hour,
            hours_elapsed=next_hour,
            food_intake=food,
        )
        estimate = values["estimate"]
        if next_hour >= near_zero_search_start:
            if estimate > NEAR_ZERO_BAC_THRESHOLD:
                has_positive_after_current = True
            elif has_positive_after_current:
                near_zero_hour = next_hour
        curve.append({
            "hour": round(next_hour, 4),
            "low": round(values["low"], 6),
            "estimate": round(estimate, 6),
            "high": round(values["high"], 6),
        })

    current_values = (
        calculate_event_aware_bac_range(
            events,
            weight_kg=weight_kg,
            r=r,
            beta_per_hour=beta_per_hour,
            hours_elapsed=current,
            food_intake=food,
        )
        if current is not None
        else None
    )

    return {
        "curve": curve,
        "current_bac": current_values,
        "estimated_near_zero_hour": near_zero_hour,
        "metadata": {
            "source": "event_aware",
            "model": EVENT_CURVE_MODEL,
            "food_intake": food,
            "step_minutes": max(1, int(step_minutes)),
            "valid_drink_events": len(events),
            "ignored_drink_events": ignored,
            "warnings": warnings,
        },
    }


def generate_legacy_bac_curve(
    alc_g: float,
    weight_kg: float,
    r: float,
    beta_per_hour: float,
    current_time_hours: float = 0.0,
    horizon_hours: float | None = None,
    step_minutes: int = DEFAULT_CURVE_STEP_MINUTES,
) -> dict[str, Any]:
    """Generate a simple all-at-start fallback curve for old payloads."""
    step = max(1, int(step_minutes)) / 60.0
    current = max(0.0, current_time_hours)
    horizon = horizon_hours if horizon_hours is not None else max(current + 4.0, 8.0)
    horizon = clamp(horizon, current, 24.0)
    hours = _curve_hours(
        current_time_hours=current,
        last_drink_time=0.0,
        step_hours=step,
        horizon_hours=horizon,
    )
    curve = []
    near_zero_hour = None
    has_positive_after_current = False
    for hour in hours:
        values = calculate_bac_range(
            alc_g=alc_g,
            weight_kg=weight_kg,
            r=r,
            beta_per_hour=beta_per_hour,
            hours_elapsed=hour,
        )
        estimate = values["estimate"]
        if hour >= current:
            if estimate > NEAR_ZERO_BAC_THRESHOLD:
                has_positive_after_current = True
            elif has_positive_after_current and near_zero_hour is None:
                near_zero_hour = hour
        curve.append({
            "hour": round(hour, 4),
            "low": round(values["low"], 6),
            "estimate": round(estimate, 6),
            "high": round(values["high"], 6),
        })

    return {
        "curve": curve,
        "estimated_near_zero_hour": near_zero_hour,
        "metadata": {
            "source": "legacy_total_grams",
            "model": "legacy_total_grams_all_at_start",
            "food_intake": "none",
            "step_minutes": max(1, int(step_minutes)),
            "valid_drink_events": 0,
            "ignored_drink_events": 0,
            "warnings": ["legacy_total_grams_curve"],
        },
    }


# ── Backwards-compatibility wrapper ───────────────────────────────────────

def BACCalculator(
    alc_g: float,
    weight: float,
    r: float,
    beta: float = DEFAULT_BETA_PER_HOUR,
    time: float = 0.0,
) -> float:
    """Deprecated wrapper; use calculate_bac()."""
    return calculate_bac(alc_g=alc_g, weight_kg=weight, r=r, beta_per_hour=beta, hours_elapsed=time)
