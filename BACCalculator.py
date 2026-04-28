"""Deterministic BAC helper functions for a Widmark-style scaffold.

Unit contract used throughout this module:
- alcohol input: grams ethanol
- weight input: kilograms
- height input: centimeters
- time input: hours
- BAC output: display-scale decimal (for example, 0.08 means 0.08 BAC)
- beta: BAC units per hour (for example, 0.015 BAC/hour)
- r: dimensionless distribution ratio
"""

from __future__ import annotations

from typing import Iterable


DEFAULT_BETA_PER_HOUR = 0.015
DEFAULT_BETA_SD = 0.0025
MIN_R = 0.45
MAX_R = 0.80
MIN_BETA_PER_HOUR = 0.005
MAX_BETA_PER_HOUR = 0.030

# Linear regression coefficients for r estimation.
# NOTE: These are currently hardcoded placeholders unless source/provenance is
# documented elsewhere in the project. Future fitted regression/statistical
# models should replace these internals while preserving the public helpers.
m_i = 0.3901319484
m_age = 0.0003273190
m_weight = -0.0009810014
m_height = 0.0011555900
m_low = 0.1173256496
m_mid = 0.0633215674

f_i = 0.3945319640
f_age = 0.0001213782
f_weight = -0.0014620109
f_height = 0.0009572304
f_low = 0.1155135171
f_mid = 0.0605819172

n_i = 0.2181713778
n_age = -0.0002123286
n_weight = -0.0011931574
n_height = 0.0021444658
n_low = 0.1388081199
n_mid = 0.0756061038


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp value to the inclusive [lower, upper] interval."""
    return max(lower, min(value, upper))


def validate_positive_number(value: float, name: str) -> None:
    """Raise ValueError when value is not a finite positive number."""
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number.")


def validate_nonnegative_number(value: float, name: str) -> None:
    """Raise ValueError when value is not a finite nonnegative number."""
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a nonnegative number.")


def _normalize_gender(gender: str | None) -> str:
    if gender is None:
        return "neutral"
    g = str(gender).strip().lower()
    if g in {"m", "male"}:
        return "male"
    if g in {"f", "female"}:
        return "female"
    return "neutral"


def _normalize_fat_level(fat: str | None) -> str:
    """Map fat inputs to low/mid/high; unknown values default to high baseline."""
    if fat is None:
        return "high"
    normalized = str(fat).strip().lower()
    if normalized in {"low"}:
        return "low"
    if normalized in {"mid", "medium"}:
        return "mid"
    return "high"


def r_coefficient(
    gender: str | None,
    age: float,
    weight: float,
    height: float,
    fat: str | None = None,
) -> float:
    """Estimate Widmark r using placeholder linear coefficients.

    Args:
        gender: Accepts "m"/"male", "f"/"female", or any other value for neutral.
        age: Age in years. Must be positive.
        weight: Body weight in kilograms. Must be positive.
        height: Body height in centimeters. Must be positive.
        fat: Body fat band. Supports "low", "mid"/"medium", "high", or None.
            Unknown values default to the baseline/high branch (no additive low/mid bump).

    Returns:
        Clamped r value in [MIN_R, MAX_R].
    """
    validate_positive_number(age, "age")
    validate_positive_number(weight, "weight")
    validate_positive_number(height, "height")

    g = _normalize_gender(gender)
    fat_level = _normalize_fat_level(fat)

    if g == "male":
        r_val = m_i + m_age * age + m_weight * weight + m_height * height
        if fat_level == "low":
            r_val += m_low
        elif fat_level == "mid":
            r_val += m_mid
    elif g == "female":
        r_val = f_i + f_age * age + f_weight * weight + f_height * height
        if fat_level == "low":
            r_val += f_low
        elif fat_level == "mid":
            r_val += f_mid
    else:
        r_val = n_i + n_age * age + n_weight * weight + n_height * height
        if fat_level == "low":
            r_val += n_low
        elif fat_level == "mid":
            r_val += n_mid

    return clamp(r_val, MIN_R, MAX_R)


def personalize_beta(
    prior_beta: float = DEFAULT_BETA_PER_HOUR,
    session_implied_betas: list[float] | None = None,
    prior_weight: float = 10.0,
) -> float:
    """Simple shrinkage estimator for beta (placeholder Bayesian-style logic).

    This is intentionally a lightweight deterministic approximation, not a full
    Bayesian posterior model. It shrinks a session mean toward a population prior.
    """
    validate_positive_number(prior_beta, "prior_beta")
    validate_positive_number(prior_weight, "prior_weight")

    if not session_implied_betas:
        return clamp(prior_beta, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)

    valid_betas = [
        float(beta)
        for beta in session_implied_betas
        if isinstance(beta, (int, float)) and beta > 0
    ]
    if not valid_betas:
        return clamp(prior_beta, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)

    n = len(valid_betas)
    session_mean = sum(valid_betas) / n
    personalized = (prior_weight * prior_beta + n * session_mean) / (prior_weight + n)
    return clamp(personalized, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)


def estimate_beta(
    profile: dict | None = None,
    session_history: Iterable[float] | None = None,
) -> float:
    """Return a conservative deterministic beta estimate.

    Currently returns population default unless valid session-implied betas
    are provided. `profile` is reserved for future deterministic adjustments.
    """
    _ = profile  # reserved for future use
    if session_history is None:
        return clamp(DEFAULT_BETA_PER_HOUR, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)

    return personalize_beta(
        prior_beta=DEFAULT_BETA_PER_HOUR,
        session_implied_betas=list(session_history),
    )


def calculate_bac(
    alc_g: float,
    weight_kg: float,
    r: float,
    beta_per_hour: float = DEFAULT_BETA_PER_HOUR,
    hours_elapsed: float = 0.0,
) -> float:
    """Calculate BAC using Widmark-style mass balance.

    Returns BAC in display-scale decimal convention (for example, 0.08 means 0.08 BAC).
    """
    validate_nonnegative_number(alc_g, "alc_g")
    validate_positive_number(weight_kg, "weight_kg")
    validate_positive_number(r, "r")
    validate_nonnegative_number(beta_per_hour, "beta_per_hour")
    validate_nonnegative_number(hours_elapsed, "hours_elapsed")

    r_clamped = clamp(r, MIN_R, MAX_R)
    beta_clamped = clamp(beta_per_hour, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)
    weight_g = weight_kg * 1000.0

    raw_bac = alc_g / (weight_g * r_clamped)
    current_bac = raw_bac - beta_clamped * hours_elapsed
    return max(current_bac, 0.0)


def calculate_bac_range(
    alc_g: float,
    weight_kg: float,
    r: float,
    beta_per_hour: float = DEFAULT_BETA_PER_HOUR,
    hours_elapsed: float = 0.0,
    r_margin: float = 0.05,
    beta_margin: float = 0.0025,
) -> dict:
    """Return a simple low/estimate/high BAC range using conservative perturbations."""
    validate_nonnegative_number(r_margin, "r_margin")
    validate_nonnegative_number(beta_margin, "beta_margin")

    estimate = calculate_bac(
        alc_g=alc_g,
        weight_kg=weight_kg,
        r=r,
        beta_per_hour=beta_per_hour,
        hours_elapsed=hours_elapsed,
    )

    # Lower BAC uses optimistic dispersion and elimination (higher r, higher beta).
    low = calculate_bac(
        alc_g=alc_g,
        weight_kg=weight_kg,
        r=clamp(r + r_margin, MIN_R, MAX_R),
        beta_per_hour=clamp(beta_per_hour + beta_margin, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR),
        hours_elapsed=hours_elapsed,
    )
    # Higher BAC uses conservative dispersion and elimination (lower r, lower beta).
    high = calculate_bac(
        alc_g=alc_g,
        weight_kg=weight_kg,
        r=clamp(r - r_margin, MIN_R, MAX_R),
        beta_per_hour=clamp(beta_per_hour - beta_margin, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR),
        hours_elapsed=hours_elapsed,
    )

    ordered = sorted([low, estimate, high])
    return {"low": max(ordered[0], 0.0), "estimate": max(ordered[1], 0.0), "high": max(ordered[2], 0.0)}


def BACCalculator(
    alc_g: float,
    weight: float,
    r: float,
    beta: float = DEFAULT_BETA_PER_HOUR,
    time: float = 0.0,
) -> float:
    """Deprecated wrapper for backwards compatibility; use calculate_bac()."""
    return calculate_bac(
        alc_g=alc_g,
        weight_kg=weight,
        r=r,
        beta_per_hour=beta,
        hours_elapsed=time,
    )
