"""Bayesian beta personalization utilities.

This module estimates a personalized alcohol elimination rate, beta, from
review-derived session estimates. Beta is represented in BAC display units per
hour: ``0.015`` means estimated BAC declines by about 0.015 per hour. These
values are approximate product-personalization signals, not medical certainty.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


DEFAULT_POPULATION_BETA = 0.015
DEFAULT_PRIOR_SD = 0.0025
DEFAULT_MIN_BETA = 0.005
DEFAULT_MAX_BETA = 0.030
DEFAULT_POPULATION_BLEND_WEIGHT = 0.10
DEFAULT_MIN_OBSERVED_SD = 0.0015


def clamp_beta(value: float, min_beta: float = DEFAULT_MIN_BETA, max_beta: float = DEFAULT_MAX_BETA) -> float:
    """Clamp beta to a plausible BAC-points-per-hour range."""
    return max(min_beta, min(float(value), max_beta))


def _coerce_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sanitize_beta_bounds(min_beta: Any, max_beta: Any, warnings: list[str]) -> tuple[float, float]:
    min_value = _coerce_finite_float(min_beta)
    max_value = _coerce_finite_float(max_beta)
    if min_value is None or max_value is None or min_value <= 0 or max_value <= min_value:
        warnings.append("invalid_beta_bounds_defaulted")
        return DEFAULT_MIN_BETA, DEFAULT_MAX_BETA
    return min_value, max_value


def _sanitize_positive(value: Any, default: float, name: str, warnings: list[str]) -> float:
    number = _coerce_finite_float(value)
    if number is None or number <= 0:
        warnings.append(f"invalid_{name}_defaulted")
        return default
    return number


def _sanitize_blend_weight(value: Any, warnings: list[str]) -> float:
    number = _coerce_finite_float(value)
    if number is None:
        warnings.append("invalid_population_blend_weight_defaulted")
        return DEFAULT_POPULATION_BLEND_WEIGHT
    clamped = max(0.0, min(number, 1.0))
    if clamped != number:
        warnings.append("population_blend_weight_clamped")
    return clamped


def filter_valid_betas(
    observed_betas: Iterable[Any] | None,
    min_beta: float = DEFAULT_MIN_BETA,
    max_beta: float = DEFAULT_MAX_BETA,
) -> tuple[list[float], int]:
    """Return valid beta observations and the count of excluded values."""
    if observed_betas is None:
        return [], 0

    try:
        iterator = iter(observed_betas)
    except TypeError:
        return [], 1

    valid: list[float] = []
    excluded = 0
    for raw in iterator:
        beta = _coerce_finite_float(raw)
        if beta is None or beta <= 0 or beta < min_beta or beta > max_beta:
            excluded += 1
            continue
        valid.append(beta)
    return valid, excluded


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _population_sd(values: list[float], mean: float) -> float:
    sd = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    return 0.0 if sd < 1e-12 else sd


def normal_posterior_mean(
    observed_mean: float,
    observed_sd: float,
    n_observations: int,
    population_beta: float = DEFAULT_POPULATION_BETA,
    prior_sd: float = DEFAULT_PRIOR_SD,
) -> float:
    """Compute the normal-normal posterior mean for beta.

    Args:
        observed_mean: Mean beta from valid observed sessions.
        observed_sd: Effective observed standard deviation used for posterior
            math. Callers should enforce a positive lower bound.
        n_observations: Number of valid observed beta estimates.
        population_beta: Prior mean beta in BAC display units per hour.
        prior_sd: Prior standard deviation.
    """
    if n_observations <= 0:
        raise ValueError("n_observations must be positive.")
    if observed_sd <= 0:
        raise ValueError("observed_sd must be positive.")
    if prior_sd <= 0:
        raise ValueError("prior_sd must be positive.")

    posterior_variance = 1.0 / (1.0 / prior_sd**2 + n_observations / observed_sd**2)
    return posterior_variance * (
        population_beta / prior_sd**2
        + n_observations * observed_mean / observed_sd**2
    )


def normal_posterior(data: Iterable[Any], sigma: float, mu0: float, tau0: float) -> float:
    """Compatibility wrapper for the prototype function name.

    Prefer ``normal_posterior_mean`` or ``estimate_personalized_beta`` for new
    code. ``data`` is filtered to finite numeric values before computing a mean.
    """
    values, _ = filter_valid_betas(data, min_beta=0.0, max_beta=float("inf"))
    if not values:
        raise ValueError("data must contain at least one finite positive beta.")
    sigma_value = _coerce_finite_float(sigma)
    mu0_value = _coerce_finite_float(mu0)
    tau0_value = _coerce_finite_float(tau0)
    effective_sigma = max(sigma_value or DEFAULT_MIN_OBSERVED_SD, DEFAULT_MIN_OBSERVED_SD)
    effective_mu0 = mu0_value if mu0_value is not None else DEFAULT_POPULATION_BETA
    effective_tau0 = tau0_value if tau0_value is not None and tau0_value > 0 else DEFAULT_PRIOR_SD
    return normal_posterior_mean(_mean(values), effective_sigma, len(values), effective_mu0, effective_tau0)


def estimate_personalized_beta(
    observed_betas: Iterable[Any] | None,
    population_beta: float = DEFAULT_POPULATION_BETA,
    prior_sd: float = DEFAULT_PRIOR_SD,
    min_beta: float = DEFAULT_MIN_BETA,
    max_beta: float = DEFAULT_MAX_BETA,
    population_blend_weight: float = DEFAULT_POPULATION_BLEND_WEIGHT,
    min_observed_sd: float = DEFAULT_MIN_OBSERVED_SD,
) -> dict[str, Any]:
    """Estimate a personalized beta from session-implied beta observations.

    Beta is measured in BAC display units per hour. For example, ``0.015``
    means estimated BAC declines by about 0.015 per hour. The output is intended
    for conservative product personalization, not as a legal or medical truth.
    """
    warnings: list[str] = []
    min_beta, max_beta = _sanitize_beta_bounds(min_beta, max_beta, warnings)
    population_beta = _sanitize_positive(population_beta, DEFAULT_POPULATION_BETA, "population_beta", warnings)
    prior_sd = _sanitize_positive(prior_sd, DEFAULT_PRIOR_SD, "prior_sd", warnings)
    min_observed_sd = _sanitize_positive(
        min_observed_sd,
        DEFAULT_MIN_OBSERVED_SD,
        "min_observed_sd",
        warnings,
    )
    population_blend_weight = _sanitize_blend_weight(population_blend_weight, warnings)
    population_beta = clamp_beta(population_beta, min_beta, max_beta)

    valid_betas, sessions_excluded = filter_valid_betas(observed_betas, min_beta, max_beta)
    sessions_used = len(valid_betas)

    if sessions_used == 0:
        return {
            "beta": population_beta,
            "source": "population",
            "sessions_used": 0,
            "sessions_excluded": sessions_excluded,
            "population_beta": population_beta,
            "observed_mean": None,
            "observed_sd": None,
            "posterior_beta": None,
            "population_blend_weight": population_blend_weight,
            "personal_weight": 0.0,
            "population_weight": 1.0,
            "min_beta": min_beta,
            "max_beta": max_beta,
            "warnings": warnings,
        }

    observed_mean = _mean(valid_betas)

    if sessions_used == 1:
        final_beta = clamp_beta(0.5 * population_beta + 0.5 * observed_mean, min_beta, max_beta)
        return {
            "beta": final_beta,
            "source": "single_session_average",
            "sessions_used": 1,
            "sessions_excluded": sessions_excluded,
            "population_beta": population_beta,
            "observed_mean": observed_mean,
            "observed_sd": None,
            "posterior_beta": None,
            "population_blend_weight": population_blend_weight,
            "personal_weight": 0.5,
            "population_weight": 0.5,
            "min_beta": min_beta,
            "max_beta": max_beta,
            "warnings": warnings,
        }

    observed_sd = _population_sd(valid_betas, observed_mean)
    effective_observed_sd = observed_sd
    if observed_sd < min_observed_sd:
        effective_observed_sd = min_observed_sd
        warnings.append("observed_sd_below_minimum_for_posterior")

    posterior_beta = normal_posterior_mean(
        observed_mean=observed_mean,
        observed_sd=effective_observed_sd,
        n_observations=sessions_used,
        population_beta=population_beta,
        prior_sd=prior_sd,
    )
    blended_beta = posterior_beta * (1.0 - population_blend_weight) + population_beta * population_blend_weight
    final_beta = clamp_beta(blended_beta, min_beta, max_beta)
    if final_beta != blended_beta:
        warnings.append("final_beta_clamped")

    return {
        "beta": final_beta,
        "source": "bayesian_personalized",
        "sessions_used": sessions_used,
        "sessions_excluded": sessions_excluded,
        "population_beta": population_beta,
        "observed_mean": observed_mean,
        "observed_sd": observed_sd,
        "posterior_beta": posterior_beta,
        "population_blend_weight": population_blend_weight,
        "personal_weight": 1.0 - population_blend_weight,
        "population_weight": population_blend_weight,
        "min_beta": min_beta,
        "max_beta": max_beta,
        "warnings": warnings,
    }


__all__ = [
    "clamp_beta",
    "filter_valid_betas",
    "normal_posterior",
    "normal_posterior_mean",
    "estimate_personalized_beta",
]
