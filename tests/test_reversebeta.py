import contextlib
import importlib
import io
import unittest

import reversebeta
from reversebeta import (
    absorbed_grams,
    estimate_implied_beta_from_session,
    normalize_food_intake,
)


class ReverseBetaTests(unittest.TestCase):
    def test_one_drink_simple_case_returns_plausible_implied_beta(self):
        peak_bac = 42 / (70 * 10 * 0.6)
        felt_sober = (peak_bac - 0.02) / 0.015
        result = estimate_implied_beta_from_session(
            grams_by_drink=[42],
            drink_times_hours=[0],
            felt_sober_hours=felt_sober,
            food_intake="none",
            weight_kg=70,
            r=0.6,
        )
        self.assertTrue(result["usable_for_personalization"])
        self.assertAlmostEqual(result["implied_beta"], 0.015, places=4)
        self.assertEqual(result["effective_drink_count"], 1)
        self.assertAlmostEqual(result["estimated_peak_bac"], peak_bac)

    def test_multiple_drinks_with_event_times_returns_metadata(self):
        result = estimate_implied_beta_from_session(
            grams_by_drink=[14, 14, 14],
            drink_times_hours=[0, 1, 2],
            felt_sober_hours=5.5,
            food_intake="medium",
            weight_kg=70,
            r=0.6,
        )
        self.assertEqual(result["method"], "event_aware_absorption_reverse_beta_v1")
        self.assertEqual(result["food_intake"], "medium")
        self.assertEqual(result["effective_drink_count"], 3)
        self.assertEqual(result["effective_grams"], 42)
        self.assertIn("units", result)

    def test_food_labels_normalize_including_old_mid(self):
        self.assertEqual(normalize_food_intake(None), "none")
        self.assertEqual(normalize_food_intake(""), "none")
        self.assertEqual(normalize_food_intake("Low"), "low")
        self.assertEqual(normalize_food_intake("Mid"), "medium")
        self.assertEqual(normalize_food_intake("Medium"), "medium")
        self.assertEqual(normalize_food_intake("High"), "high")
        self.assertEqual(normalize_food_intake("mystery"), "none")

    def test_high_food_absorbs_slower_than_none_at_same_early_time(self):
        none_absorbed = absorbed_grams("none", 14, 0, 0.3)
        high_absorbed = absorbed_grams("high", 14, 0, 0.3)
        self.assertEqual(none_absorbed, 14)
        self.assertLess(high_absorbed, none_absorbed)

    def test_mismatched_grams_and_times_is_unusable(self):
        result = estimate_implied_beta_from_session(
            grams_by_drink=[14, 14],
            drink_times_hours=[0],
            felt_sober_hours=4,
            weight_kg=70,
            r=0.6,
        )
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("mismatched_drink_grams_and_times", result["validity_flags"])
        self.assertIsNone(result["implied_beta"])

    def test_sober_time_before_effective_start_is_invalid(self):
        result = estimate_implied_beta_from_session(
            grams_by_drink=[14, 14],
            drink_times_hours=[0, 3],
            felt_sober_hours=2.5,
            weight_kg=70,
            r=0.6,
        )
        self.assertFalse(result["usable_for_personalization"])
        self.assertIn("effective_start_reset_after_likely_zero_bac", result["validity_flags"])
        self.assertIn("felt_sober_not_after_effective_start", result["validity_flags"])

    def test_vomiting_returns_unusable_or_low_confidence(self):
        result = estimate_implied_beta_from_session(
            grams_by_drink=[42],
            drink_times_hours=[0],
            felt_sober_hours=5.0,
            weight_kg=70,
            r=0.6,
            vomited=True,
        )
        self.assertFalse(result["usable_for_personalization"])
        self.assertLessEqual(result["confidence"], 0.2)
        self.assertIn("vomiting_reported_unreliable_for_personalization", result["validity_flags"])

    def test_blackout_adds_validity_flag_and_reduces_confidence(self):
        result = estimate_implied_beta_from_session(
            grams_by_drink=[42],
            drink_times_hours=[0],
            felt_sober_hours=5.0,
            weight_kg=70,
            r=0.6,
            blackout=True,
        )
        self.assertIn("blackout_reported_reduces_confidence", result["validity_flags"])
        self.assertLess(result["confidence"], 1.0)

    def test_out_of_range_raw_beta_is_flagged_and_confidence_reduced(self):
        result = estimate_implied_beta_from_session(
            grams_by_drink=[42],
            drink_times_hours=[0],
            felt_sober_hours=0.1,
            weight_kg=70,
            r=0.6,
        )
        self.assertEqual(result["implied_beta"], 0.030)
        self.assertIn("raw_implied_beta_outside_plausible_range_clipped", result["validity_flags"])
        self.assertLess(result["confidence"], 1.0)

    def test_importing_reversebeta_has_no_print_side_effects(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            importlib.reload(reversebeta)
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
