import unittest

from server import predict_from_payload, implied_beta_from_payload
from BACCalculator import (
    implied_beta_from_session,
    population_beta_prior,
    personalize_beta,
    estimate_beta,
    MIN_BETA_PER_HOUR, MAX_BETA_PER_HOUR,
)


class PredictEndpointLogicTests(unittest.TestCase):
    def _valid_payload(self):
        return {
            "profile": {
                "sex": "male",
                "age_years": 27,
                "height_cm": 178.0,
                "weight_kg": 72.5,
                "body_fat_percent": 18.2,
                "body_fat_bracket": "mid",
                "drinks_per_week": 7,
            },
            "session": {
                "standard_drinks": 3,
                "grams_alcohol": 42.0,
                "hours_elapsed": 2.0,
            },
        }

    def _payload_with_history(self):
        p = self._valid_payload()
        p["history"] = {"session_implied_betas": [0.012, 0.013, 0.011, 0.014, 0.012]}
        return p

    # ── shape tests ───────────────────────────────────────────────────────
    def test_predict_returns_expected_shape(self):
        result = predict_from_payload(self._valid_payload())
        self.assertEqual(result["schema_version"], 2)
        self.assertIn("units",  result)
        self.assertIn("model",  result)
        self.assertIn("bac",    result)
        self.assertIn("meta",   result)
        self.assertEqual(result["model"]["status"], "scaffold")
        self.assertEqual(result["model"]["personalization"], "not_enabled")
        self.assertEqual(result["model"]["sessions_used"], 0)

    def test_predict_with_history_activates_personalization(self):
        result = predict_from_payload(self._payload_with_history())
        self.assertEqual(result["model"]["personalization"], "bayesian_shrinkage_active")
        self.assertEqual(result["model"]["sessions_used"], 5)
        self.assertGreater(result["model"]["personal_weight_pct"], 0)

    # ── validation tests ──────────────────────────────────────────────────
    def test_predict_rejects_negative_weight(self):
        p = self._valid_payload()
        p["profile"]["weight_kg"] = -1
        with self.assertRaises(ValueError):
            predict_from_payload(p)

    def test_predict_rejects_negative_alcohol(self):
        p = self._valid_payload()
        p["session"]["grams_alcohol"] = -0.1
        with self.assertRaises(ValueError):
            predict_from_payload(p)

    def test_predict_bac_is_ordered(self):
        result = predict_from_payload(self._valid_payload())
        self.assertLessEqual(result["bac"]["low"],      result["bac"]["estimate"])
        self.assertLessEqual(result["bac"]["estimate"], result["bac"]["high"])

    def test_predict_bac_ordered_with_history(self):
        result = predict_from_payload(self._payload_with_history())
        self.assertLessEqual(result["bac"]["low"],      result["bac"]["estimate"])
        self.assertLessEqual(result["bac"]["estimate"], result["bac"]["high"])

    # ── Bayesian shrinkage tests ──────────────────────────────────────────
    def test_personalize_beta_shrinks_toward_session_mean(self):
        """More sessions → beta converges toward session mean."""
        prior = 0.015
        session_betas = [0.012] * 20
        personal = personalize_beta(prior_beta=prior, session_implied_betas=session_betas)
        self.assertLess(personal, prior)  # pulled toward 0.012
        self.assertGreaterEqual(personal, MIN_BETA_PER_HOUR)
        self.assertLessEqual(personal,    MAX_BETA_PER_HOUR)

    def test_personalize_beta_no_history_returns_prior(self):
        result = personalize_beta(prior_beta=0.015, session_implied_betas=[])
        self.assertAlmostEqual(result, 0.015, places=4)

    def test_personalize_beta_prior_dominates_early(self):
        personal_1  = personalize_beta(0.015, [0.010])
        personal_10 = personalize_beta(0.015, [0.010] * 10)
        # After 10 sessions, should be further from prior than after 1
        self.assertLess(personal_10, personal_1)

    def test_implied_beta_from_session_correct(self):
        """3 drinks (42g), 70kg, r=0.6 → peak BAC=0.1; sober at 6.67hr → beta=0.015"""
        peak = 42 / (70 * 10 * 0.6)  # 0.1
        sober_hr = peak / 0.015       # 6.666...
        beta = implied_beta_from_session(42, 70, 0.6, sober_hr)
        self.assertAlmostEqual(beta, 0.015, places=4)

    def test_implied_beta_invalid_inputs_return_none(self):
        self.assertIsNone(implied_beta_from_session(0,  70, 0.6, 4.0))
        self.assertIsNone(implied_beta_from_session(42, 70, 0.6, 0.0))
        self.assertIsNone(implied_beta_from_session(42, 0,  0.6, 4.0))

    def test_implied_beta_clamped_to_valid_range(self):
        """Very short sober time → very high implied beta, must be clamped."""
        beta = implied_beta_from_session(42, 70, 0.6, 0.1)
        self.assertLessEqual(beta, MAX_BETA_PER_HOUR)

    # ── population_beta_prior tests ───────────────────────────────────────
    def test_population_prior_adjusts_for_age_band(self):
        young  = population_beta_prior(age=22)
        middle = population_beta_prior(age=30)
        older  = population_beta_prior(age=55)
        self.assertLess(young, older)
        self.assertLessEqual(middle, older)

    def test_population_prior_adjusts_for_bmi(self):
        normal = population_beta_prior(weight_kg=70, height_cm=175)   # BMI~22.9
        obese  = population_beta_prior(weight_kg=110, height_cm=175)  # BMI~35.9
        self.assertLess(normal, obese)

    def test_population_prior_adjusts_for_drinks_per_week(self):
        light  = population_beta_prior(drinks_per_week=3)
        heavy  = population_beta_prior(drinks_per_week=25)
        self.assertLess(light, heavy)

    # ── /implied-beta endpoint ────────────────────────────────────────────
    def test_implied_beta_endpoint_returns_value(self):
        result = implied_beta_from_payload({
            "grams_alcohol": 42.0,
            "weight_kg": 70.0,
            "r": 0.6,
            "felt_sober_hours": 6.0,
        })
        self.assertIn("implied_beta", result)
        self.assertGreaterEqual(result["implied_beta"], MIN_BETA_PER_HOUR)
        self.assertLessEqual(result["implied_beta"],    MAX_BETA_PER_HOUR)

    def test_implied_beta_endpoint_rejects_zero_sober_hours(self):
        with self.assertRaises(ValueError):
            implied_beta_from_payload({
                "grams_alcohol": 42, "weight_kg": 70, "r": 0.6, "felt_sober_hours": 0
            })

    # ── estimate_beta integration ─────────────────────────────────────────
    def test_estimate_beta_with_profile_and_history(self):
        profile = {"age": 30, "weight_kg": 75, "height_cm": 178, "drinks_per_week": 10}
        history = [0.011, 0.012, 0.013]
        beta = estimate_beta(profile=profile, session_history=history)
        self.assertGreaterEqual(beta, MIN_BETA_PER_HOUR)
        self.assertLessEqual(beta,    MAX_BETA_PER_HOUR)
        # Should differ from no-profile default
        default_beta = estimate_beta()
        self.assertNotEqual(beta, default_beta)


if __name__ == "__main__":
    unittest.main()