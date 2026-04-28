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

from typing import Iterable, Optional


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
    """Back-calculate a session-implied beta from post-session review data.

    Uses: felt_sober time as a proxy for when BAC ≈ 0.
    If the user drank X grams (peak BAC = X/(W*10*r)) and felt sober after T hours,
    then: 0 = peak_BAC - beta*T  =>  beta = peak_BAC / T

    Returns:
        Implied beta clamped to valid range, or None if inputs are invalid.
    """
    if felt_sober_hours <= 0 or grams_alcohol <= 0 or weight_kg <= 0 or r <= 0:
        return None
    peak_bac = grams_alcohol / (weight_kg * 10.0 * r)
    if peak_bac <= 0:
        return None
    return clamp(peak_bac / felt_sober_hours, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)


def personalize_beta(
    prior_beta: float = DEFAULT_BETA_PER_HOUR,
    session_implied_betas: list[float] | None = None,
    prior_weight: float = PRIOR_SESSION_WEIGHT,
) -> float:
    """Bayesian shrinkage estimator for beta.

    Weighted average of population prior and user's session-implied betas.
    Formula: beta_personal = (W_prior * beta_prior + N * beta_session_mean)
                             / (W_prior + N)

    Early on (few sessions): prior dominates.
    Over time (many sessions): personal history dominates.

    At N = PRIOR_SESSION_WEIGHT sessions, weight is 50/50.

    Args:
        prior_beta:            Population or demographic prior for this user.
        session_implied_betas: List of back-calculated betas from past sessions.
        prior_weight:          Effective session count the prior is worth.

    Returns:
        Personalized beta clamped to [MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR].
    """
    validate_positive_number(prior_beta,   "prior_beta")
    validate_positive_number(prior_weight, "prior_weight")

    if not session_implied_betas:
        return clamp(prior_beta, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)

    valid_betas = [
        float(b) for b in session_implied_betas
        if isinstance(b, (int, float)) and MIN_BETA_PER_HOUR <= b <= MAX_BETA_PER_HOUR
    ]
    if not valid_betas:
        return clamp(prior_beta, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)

    n            = len(valid_betas)
    session_mean = sum(valid_betas) / n
    personalized = (prior_weight * prior_beta + n * session_mean) / (prior_weight + n)
    return clamp(personalized, MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR)


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