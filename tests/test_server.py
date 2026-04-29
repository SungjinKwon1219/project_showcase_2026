import unittest

from server import (
    body_fat_bucket_from_percent,
    derive_body_fat_bracket,
    predict_from_payload,
    implied_beta_from_payload,
)
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

    def _payload_with_one_history_entry(self):
        p = self._valid_payload()
        p["history"] = {"session_implied_betas": [0.011]}
        return p

    def _payload_with_drink_events(self):
        p = self._valid_payload()
        p["session"].update({
            "grams_alcohol": 42.0,
            "standard_drinks": 3,
            "hours_elapsed": 1.0,
            "food_intake": "none",
            "drink_events": [
                {"grams_alcohol": 14, "hours_from_session_start": 0.0},
                {"grams_alcohol": 28, "hours_from_session_start": 2.0},
            ],
        })
        return p

    def _valid_implied_beta_payload(self):
        return {
            "session_id": "session-test",
            "profile": {"weight_kg": 70.0, "r": 0.6},
            "drink_events": [{"grams_alcohol": 42.0, "hours_from_session_start": 0.0}],
            "near_baseline_hours": 6.0,
            "food_intake": "none",
            "missed_drinks": "no",
            "drink_log_confidence": "high",
            "drink_timing_confidence": "high",
            "vomited": False,
            "blackout": False,
            "memory_gap": False,
            "prior_beta": 0.015,
        }

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
        self.assertIn("beta_metadata", result)
        self.assertEqual(result["beta_metadata"]["source"], "population")
        self.assertEqual(result["beta_metadata"]["sessions_used"], 0)
        self.assertEqual(result["model"]["beta_per_hour"], result["beta_metadata"]["value"])
        self.assertEqual(result["personalization"]["calibration_type"], "limited_beta_only")
        self.assertFalse(result["personalization"]["active"])
        self.assertIn("curve", result)
        self.assertEqual(result["curve_metadata"]["source"], "legacy_total_grams")

    def test_predict_with_history_activates_personalization(self):
        result = predict_from_payload(self._payload_with_history())
        self.assertEqual(result["model"]["personalization"], "bayesian_shrinkage_active")
        self.assertEqual(result["model"]["sessions_used"], 5)
        self.assertGreater(result["model"]["personal_weight_pct"], 0)
        self.assertTrue(result["personalization"]["active"])
        self.assertEqual(result["personalization"]["calibration_type"], "limited_beta_only")

    def test_predict_one_history_entry_uses_single_session_average(self):
        result = predict_from_payload(self._payload_with_one_history_entry())
        meta = result["beta_metadata"]
        expected = (meta["population_beta"] + 0.011) / 2
        self.assertEqual(meta["source"], "single_session_average")
        self.assertEqual(meta["sessions_used"], 1)
        self.assertAlmostEqual(meta["value"], expected, places=6)
        self.assertEqual(result["model"]["beta_source"], "single_session_average")

    def test_predict_two_or_more_history_entries_uses_bayesian_personalized(self):
        result = predict_from_payload(self._payload_with_history())
        self.assertEqual(result["beta_metadata"]["source"], "bayesian_personalized")

    def test_predict_ignores_invalid_beta_history_values(self):
        p = self._valid_payload()
        p["history"] = {
            "session_implied_betas": [
                0.012,
                0.20,
                "not-a-beta",
                {"implied_beta": 0.011, "usable_for_personalization": False},
            ]
        }
        result = predict_from_payload(p)
        self.assertEqual(result["beta_metadata"]["sessions_used"], 1)
        self.assertEqual(result["beta_metadata"]["sessions_excluded"], 3)

    def test_predict_accepts_old_numeric_beta_history(self):
        result = predict_from_payload(self._payload_with_history())
        self.assertEqual(result["beta_metadata"]["sessions_used"], 5)
        self.assertEqual(result["model"]["sessions_used"], 5)

    def test_predict_accepts_new_object_beta_history(self):
        p = self._valid_payload()
        p["history"] = {
            "session_implied_betas": [
                {"implied_beta": 0.012, "usable_for_personalization": True, "confidence": 0.8},
                {"implied_beta_result": {"implied_beta": 0.013, "usable_for_personalization": True}},
            ]
        }
        result = predict_from_payload(p)
        self.assertEqual(result["beta_metadata"]["sessions_used"], 2)
        self.assertEqual(result["beta_metadata"]["source"], "bayesian_personalized")

    def test_predict_ignores_unusable_object_beta_history(self):
        p = self._valid_payload()
        p["history"] = {
            "session_implied_betas": [
                {"implied_beta": 0.012, "usable_for_personalization": False},
                {"implied_beta": 0.013, "usable_for_personalization": True},
            ]
        }
        result = predict_from_payload(p)
        self.assertEqual(result["beta_metadata"]["sessions_used"], 1)
        self.assertEqual(result["beta_metadata"]["sessions_excluded"], 1)

    def test_predict_applies_usable_feedback_limited_beta_only_to_current_bac(self):
        baseline = predict_from_payload(self._valid_payload())
        calibrated_payload = self._valid_payload()
        calibrated_payload["history"] = {
            "session_implied_betas": [
                {"implied_beta": 0.010, "usable_for_personalization": True, "confidence": 0.9},
            ]
        }

        calibrated = predict_from_payload(calibrated_payload)

        self.assertEqual(calibrated["model"]["personalization"], "bayesian_shrinkage_active")
        self.assertEqual(calibrated["beta_metadata"]["sessions_used"], 1)
        self.assertLess(calibrated["model"]["beta_per_hour"], baseline["model"]["beta_per_hour"])
        self.assertGreater(calibrated["bac"]["estimate"], baseline["bac"]["estimate"])

    def test_predict_reports_active_limited_beta_personalization_metadata(self):
        payload = self._valid_payload()
        payload["history"] = {
            "session_implied_betas": [
                {"implied_beta": 0.010, "usable_for_personalization": True, "confidence": 0.9},
            ]
        }
        result = predict_from_payload(payload)

        summary = result["personalization"]
        self.assertEqual(summary["calibration_type"], "limited_beta_only")
        self.assertTrue(summary["active"])
        self.assertEqual(summary["source_count"], 1)
        self.assertEqual(summary["usable_source_count"], 1)
        self.assertNotEqual(summary["base_beta"], summary["effective_beta"])

    def test_predict_reports_inactive_limited_beta_personalization_metadata(self):
        result = predict_from_payload(self._valid_payload())

        summary = result["personalization"]
        self.assertEqual(summary["calibration_type"], "limited_beta_only")
        self.assertFalse(summary["active"])
        self.assertEqual(summary["source_count"], 0)
        self.assertEqual(summary["usable_source_count"], 0)
        self.assertEqual(summary["base_beta"], summary["effective_beta"])

    def test_predict_default_allows_active_limited_personalization_when_usable_signals_exist(self):
        payload = self._valid_payload()
        payload["history"] = {
            "session_implied_betas": [
                {"implied_beta": 0.010, "usable_for_personalization": True, "confidence": 0.9},
            ]
        }

        result = predict_from_payload(payload)

        self.assertTrue(result["personalization"]["active"])
        self.assertFalse(result["personalization"]["disabled_by_user"])
        self.assertNotEqual(
            result["personalization"]["base_beta"],
            result["personalization"]["effective_beta"],
        )

    def test_predict_disabled_limited_personalization_uses_base_beta_with_counts_visible(self):
        baseline = predict_from_payload(self._valid_payload())
        payload = self._valid_payload()
        payload["history"] = {
            "session_implied_betas": [
                {"implied_beta": 0.010, "usable_for_personalization": True, "confidence": 0.9},
            ]
        }
        payload["personalization_settings"] = {"limited_personalization_enabled": False}

        result = predict_from_payload(payload)

        summary = result["personalization"]
        self.assertFalse(summary["active"])
        self.assertTrue(summary["disabled_by_user"])
        self.assertEqual(summary["source_count"], 1)
        self.assertEqual(summary["usable_source_count"], 1)
        self.assertEqual(summary["base_beta"], summary["effective_beta"])
        self.assertEqual(result["model"]["beta_per_hour"], baseline["model"]["beta_per_hour"])
        self.assertEqual(result["bac"]["estimate"], baseline["bac"]["estimate"])
        self.assertIn("turned off", summary["message"])

    def test_predict_omitting_personalization_settings_keeps_calibration_when_usable_signals_exist(self):
        """Backward compatible: omitting personalization_settings behaves like personalization enabled."""
        payload = self._valid_payload()
        payload["history"] = self._payload_with_history()["history"]
        self.assertNotIn("personalization_settings", payload)

        result = predict_from_payload(payload)

        self.assertFalse(result["personalization"]["disabled_by_user"])
        self.assertTrue(result["personalization"]["active"])

    def test_predict_personalization_settings_explicit_true_matches_omitted_behavior(self):
        calibrated = predict_from_payload(self._payload_with_history())
        payload = self._payload_with_history()
        payload["personalization_settings"] = {"limited_personalization_enabled": True}

        explicit = predict_from_payload(payload)

        self.assertFalse(explicit["personalization"]["disabled_by_user"])
        self.assertEqual(
            explicit["model"]["beta_per_hour"], calibrated["model"]["beta_per_hour"]
        )
        self.assertEqual(calibrated["personalization"]["active"], explicit["personalization"]["active"])

    def test_predict_ignores_unusable_feedback_limited_beta_only_history(self):
        baseline = predict_from_payload(self._valid_payload())
        unusable_payload = self._valid_payload()
        unusable_payload["history"] = {
            "session_implied_betas": [
                {"implied_beta": 0.010, "usable_for_personalization": False, "confidence": 0.0},
            ]
        }

        result = predict_from_payload(unusable_payload)

        self.assertEqual(result["model"]["personalization"], "not_enabled")
        self.assertEqual(result["beta_metadata"]["sessions_used"], 0)
        self.assertEqual(result["beta_metadata"]["sessions_excluded"], 1)
        self.assertEqual(result["model"]["beta_per_hour"], baseline["model"]["beta_per_hour"])
        self.assertEqual(result["bac"]["estimate"], baseline["bac"]["estimate"])

    # ── body-fat bucket / coefficient philosophy tests ────────────────────
    def test_body_fat_percent_maps_to_universal_buckets(self):
        self.assertEqual(body_fat_bucket_from_percent(14.9), "low")
        self.assertEqual(body_fat_bucket_from_percent(15.0), "mid")
        self.assertEqual(body_fat_bucket_from_percent(25.0), "mid")
        self.assertEqual(body_fat_bucket_from_percent(25.1), "high")

    def test_same_body_fat_percent_bucket_across_sex_values(self):
        for sex in ("male", "female", "other"):
            profile = dict(self._valid_payload()["profile"], sex=sex, body_fat_percent=22.0)
            self.assertEqual(derive_body_fat_bracket(profile), "mid")

    def test_nearby_body_fat_percents_in_same_bucket_use_same_r_adjustment(self):
        low_mid = self._valid_payload()
        high_mid = self._valid_payload()
        low_mid["profile"]["body_fat_percent"] = 18.0
        high_mid["profile"]["body_fat_percent"] = 22.0
        low_mid["profile"]["body_fat_bracket"] = "low"
        high_mid["profile"]["body_fat_bracket"] = "high"

        self.assertEqual(predict_from_payload(low_mid)["model"]["body_fat_bracket"], "mid")
        self.assertEqual(predict_from_payload(high_mid)["model"]["body_fat_bracket"], "mid")
        self.assertEqual(
            predict_from_payload(low_mid)["model"]["r"],
            predict_from_payload(high_mid)["model"]["r"],
        )

    def test_crossing_body_fat_bucket_threshold_changes_r(self):
        low = self._valid_payload()
        mid = self._valid_payload()
        high = self._valid_payload()
        low["profile"]["body_fat_percent"] = 14.9
        mid["profile"]["body_fat_percent"] = 15.0
        high["profile"]["body_fat_percent"] = 25.1

        low_result = predict_from_payload(low)
        mid_result = predict_from_payload(mid)
        high_result = predict_from_payload(high)

        self.assertEqual(low_result["model"]["body_fat_bracket"], "low")
        self.assertEqual(mid_result["model"]["body_fat_bracket"], "mid")
        self.assertEqual(high_result["model"]["body_fat_bracket"], "high")
        self.assertNotEqual(low_result["model"]["r"], mid_result["model"]["r"])
        self.assertNotEqual(mid_result["model"]["r"], high_result["model"]["r"])

    def test_r_differs_by_sex_with_same_body_fat_percent(self):
        male = self._valid_payload()
        female = self._valid_payload()
        female["profile"]["sex"] = "female"

        male_result = predict_from_payload(male)
        female_result = predict_from_payload(female)

        self.assertEqual(male_result["model"]["body_fat_bracket"], "mid")
        self.assertEqual(female_result["model"]["body_fat_bracket"], "mid")
        self.assertNotEqual(male_result["model"]["r"], female_result["model"]["r"])

    def test_backend_prefers_percent_over_conflicting_legacy_bracket(self):
        p = self._valid_payload()
        p["profile"]["body_fat_percent"] = 22.0
        p["profile"]["body_fat_bracket"] = "high"

        result = predict_from_payload(p)
        expected_mid = self._valid_payload()
        expected_mid["profile"]["body_fat_percent"] = 22.0
        expected_mid["profile"]["body_fat_bracket"] = "mid"

        self.assertEqual(result["model"]["body_fat_bracket"], "mid")
        self.assertEqual(result["model"]["r"], predict_from_payload(expected_mid)["model"]["r"])

    def test_legacy_body_fat_bracket_still_works_without_percent(self):
        legacy = self._valid_payload()
        percent = self._valid_payload()
        del legacy["profile"]["body_fat_percent"]
        legacy["profile"]["body_fat_bracket"] = "low"
        percent["profile"]["body_fat_percent"] = 14.0
        percent["profile"]["body_fat_bracket"] = "high"

        self.assertEqual(predict_from_payload(legacy)["model"]["body_fat_bracket"], "low")
        self.assertEqual(
            predict_from_payload(legacy)["model"]["r"],
            predict_from_payload(percent)["model"]["r"],
        )

    def test_missing_body_fat_fields_default_to_high_bucket(self):
        p = self._valid_payload()
        del p["profile"]["body_fat_percent"]
        del p["profile"]["body_fat_bracket"]
        result = predict_from_payload(p)
        self.assertEqual(result["model"]["body_fat_bracket"], "high")

    def test_malformed_or_out_of_bounds_body_fat_percent_is_rejected(self):
        malformed = self._valid_payload()
        malformed["profile"]["body_fat_percent"] = "22"
        with self.assertRaises(ValueError):
            predict_from_payload(malformed)

        impossible = self._valid_payload()
        impossible["profile"]["body_fat_percent"] = 100.0
        with self.assertRaises(ValueError):
            predict_from_payload(impossible)

    def test_beta_does_not_change_when_only_sex_changes(self):
        male = self._valid_payload()
        female = self._valid_payload()
        female["profile"]["sex"] = "female"

        self.assertEqual(
            predict_from_payload(male)["model"]["beta_per_hour"],
            predict_from_payload(female)["model"]["beta_per_hour"],
        )

    def test_beta_does_not_change_when_only_body_fat_changes(self):
        low = self._valid_payload()
        high = self._valid_payload()
        low["profile"]["body_fat_percent"] = 12.0
        high["profile"]["body_fat_percent"] = 30.0
        low["profile"]["body_fat_bracket"] = "high"
        high["profile"]["body_fat_bracket"] = "low"

        self.assertEqual(
            predict_from_payload(low)["model"]["beta_per_hour"],
            predict_from_payload(high)["model"]["beta_per_hour"],
        )

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

    def test_predict_with_drink_events_uses_event_aware_source(self):
        result = predict_from_payload(self._payload_with_drink_events())
        self.assertEqual(result["curve_metadata"]["source"], "event_aware")
        self.assertEqual(result["curve_metadata"]["valid_drink_events"], 2)

    def test_predict_without_drink_events_falls_back_to_legacy(self):
        result = predict_from_payload(self._valid_payload())
        self.assertEqual(result["curve_metadata"]["source"], "legacy_total_grams")
        self.assertGreater(len(result["curve"]), 0)

    def test_predict_curve_contains_points(self):
        result = predict_from_payload(self._payload_with_drink_events())
        curve = result["curve"]
        self.assertGreater(len(curve), 0)
        self.assertEqual([p["hour"] for p in curve], sorted(p["hour"] for p in curve))
        self.assertTrue(all(p["estimate"] >= 0 for p in curve))

    def test_predict_peak_bac_is_derived_from_curve(self):
        result = predict_from_payload(self._payload_with_drink_events())
        peak_from_points = max(point["estimate"] for point in result["curve"])
        self.assertAlmostEqual(result["peak_bac"], peak_from_points, places=6)
        self.assertEqual(result["peak_status"], "future")
        self.assertGreater(result["time_to_peak_hours"], 0)

    def test_predict_current_bac_matches_curve_near_elapsed_time(self):
        result = predict_from_payload(self._payload_with_drink_events())
        point = next(p for p in result["curve"] if p["hour"] == 1.0)
        self.assertAlmostEqual(result["bac"]["estimate"], point["estimate"], places=6)

    def test_predict_event_aware_differs_from_all_at_start_for_late_drink(self):
        event_result = predict_from_payload(self._payload_with_drink_events())
        legacy_payload = self._valid_payload()
        legacy_payload["session"].update({
            "grams_alcohol": 28.0,
            "standard_drinks": 2,
            "hours_elapsed": 1.0,
        })
        legacy_result = predict_from_payload(legacy_payload)
        self.assertLess(event_result["bac"]["estimate"], legacy_result["bac"]["estimate"])

    def test_predict_food_intake_changes_event_aware_curve(self):
        no_food = predict_from_payload(self._payload_with_drink_events())
        high_food_payload = self._payload_with_drink_events()
        high_food_payload["session"]["food_intake"] = "high"
        high_food = predict_from_payload(high_food_payload)
        early_no_food = next(p for p in no_food["curve"] if p["hour"] == 0.5)
        early_high_food = next(p for p in high_food["curve"] if p["hour"] == 0.5)
        self.assertLess(early_high_food["estimate"], early_no_food["estimate"])

    def test_predict_invalid_drink_events_fall_back_without_crashing(self):
        p = self._valid_payload()
        p["session"]["drink_events"] = [
            {"grams_alcohol": "bad", "hours_from_session_start": 0},
            {"grams_alcohol": 14, "hours_from_session_start": -1},
        ]
        result = predict_from_payload(p)
        self.assertEqual(result["curve_metadata"]["source"], "legacy_total_grams")
        self.assertEqual(result["curve_metadata"]["ignored_drink_events"], 2)
        self.assertIn("falling_back_to_legacy_total_grams_curve", result["curve_metadata"]["warnings"])

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
    def test_implied_beta_can_return_usable_limited_beta_with_high_confidence_feedback(self):
        result = implied_beta_from_payload(self._valid_implied_beta_payload())
        self.assertIn("implied_beta", result)
        self.assertTrue(result["usable_for_personalization"])
        self.assertEqual(result["reason"], "usable")
        self.assertEqual(result["calibration_type"], "limited_beta_only")
        self.assertGreaterEqual(result["implied_beta"], MIN_BETA_PER_HOUR)
        self.assertLessEqual(result["implied_beta"],    MAX_BETA_PER_HOUR)

    def test_implied_beta_endpoint_zero_sober_hours_returns_unusable_metadata(self):
        payload = self._valid_implied_beta_payload()
        payload["near_baseline_hours"] = 0
        result = implied_beta_from_payload(payload)
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("near_baseline_hours_invalid", result["rejection_reasons"])

    def test_implied_beta_endpoint_new_event_aware_payload_returns_metadata(self):
        payload = {
            "profile_snapshot": {"weight_kg": 70.0, "r": 0.6},
            "drink_events": [
                {"grams_alcohol": 14, "hours_from_session_start": 0},
                {"grams": 14, "time_hours": 1.25},
                {"alcohol_grams": 14, "t": 2.0},
            ],
            "review": {
                "felt_sober_hours": 5.5,
                "food_intake": "medium",
                "final_bac_anchor": 0.02,
                "blackout": False,
                "vomited": False,
                "missed_drinks": "no",
                "drink_log_confidence": "high",
                "drink_timing_confidence": "high",
            },
            "prior_beta": 0.015,
        }
        result = implied_beta_from_payload(payload)
        self.assertEqual(result["method"], "event_aware_absorption_reverse_beta_v1")
        self.assertIn("units", result)
        self.assertIn("confidence", result)
        self.assertIn("validity_flags", result)
        self.assertIn("usable_for_personalization", result)
        self.assertEqual(result["effective_drink_count"], 3)

    def test_implied_beta_endpoint_vomiting_returns_unusable(self):
        payload = self._valid_implied_beta_payload()
        payload["vomited"] = True
        result = implied_beta_from_payload(payload)
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("vomiting_reported", result["rejection_reasons"])

    def test_implied_beta_rejects_missed_drinks_limited_beta_only(self):
        payload = self._valid_implied_beta_payload()
        payload["missed_drinks"] = "some"
        result = implied_beta_from_payload(payload)
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("missed_drinks_not_no", result["rejection_reasons"])

    def test_implied_beta_rejects_drink_log_confidence_not_high_limited_beta_only(self):
        payload = self._valid_implied_beta_payload()
        payload["drink_log_confidence"] = "medium"
        result = implied_beta_from_payload(payload)
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("drink_log_confidence_not_high", result["rejection_reasons"])

    def test_implied_beta_rejects_drink_timing_confidence_not_high_limited_beta_only(self):
        payload = self._valid_implied_beta_payload()
        payload["drink_timing_confidence"] = "low"
        result = implied_beta_from_payload(payload)
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("drink_timing_confidence_not_high", result["rejection_reasons"])

    def test_implied_beta_rejects_blackout_limited_beta_only(self):
        payload = self._valid_implied_beta_payload()
        payload["blackout"] = True
        result = implied_beta_from_payload(payload)
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("blackout_reported", result["rejection_reasons"])

    def test_implied_beta_rejects_memory_gap_limited_beta_only(self):
        payload = self._valid_implied_beta_payload()
        payload["memory_gap"] = True
        result = implied_beta_from_payload(payload)
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("memory_gap_reported", result["rejection_reasons"])

    def test_implied_beta_rejects_missing_confidence_limited_beta_only(self):
        result = implied_beta_from_payload({
            "profile": {"weight_kg": 70.0, "r": 0.6},
            "drink_events": [{"grams_alcohol": 42.0, "hours_from_session_start": 0.0}],
            "near_baseline_hours": 6.0,
        })
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("missed_drinks_not_no", result["rejection_reasons"])
        self.assertIn("drink_log_confidence_not_high", result["rejection_reasons"])
        self.assertIn("drink_timing_confidence_not_high", result["rejection_reasons"])

    def test_malformed_implied_beta_payload_returns_structured_unusable_result(self):
        payload = self._valid_implied_beta_payload()
        del payload["drink_events"]
        result = implied_beta_from_payload(payload)
        self.assertFalse(result["usable_for_personalization"])
        self.assertEqual(result["calibration_type"], "limited_beta_only")
        self.assertIn("missing_drink_events", result["rejection_reasons"])

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
