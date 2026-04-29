import unittest

from BACCalculator import (
    MAX_BETA_PER_HOUR,
    MAX_R,
    MIN_BETA_PER_HOUR,
    MIN_R,
    calculate_bac,
    calculate_bac_range,
    event_aware_bac_at_time,
    estimate_beta,
    generate_event_aware_bac_curve,
    r_coefficient,
)


class BACCalculatorTests(unittest.TestCase):
    def test_zero_alcohol_returns_zero(self) -> None:
        self.assertEqual(calculate_bac(alc_g=0.0, weight_kg=70.0, r=0.6), 0.0)

    def test_elapsed_time_reduces_bac(self) -> None:
        bac_now = calculate_bac(alc_g=42.0, weight_kg=70.0, r=0.6, hours_elapsed=0.0)
        bac_later = calculate_bac(alc_g=42.0, weight_kg=70.0, r=0.6, hours_elapsed=1.0)
        self.assertLess(bac_later, bac_now)

    def test_bac_never_below_zero(self) -> None:
        bac = calculate_bac(
            alc_g=14.0,
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.03,
            hours_elapsed=20.0,
        )
        self.assertEqual(bac, 0.0)

    def test_invalid_weight_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            calculate_bac(alc_g=14.0, weight_kg=0.0, r=0.6)

    def test_invalid_r_inputs_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            r_coefficient(gender="m", age=0, weight=70, height=175, fat="mid")
        with self.assertRaises(ValueError):
            r_coefficient(gender="m", age=25, weight=0, height=175, fat="mid")
        with self.assertRaises(ValueError):
            r_coefficient(gender="m", age=25, weight=70, height=0, fat="mid")

    def test_male_mid_fat_branch_works(self) -> None:
        r_val = r_coefficient(gender="m", age=25, weight=70, height=175, fat="mid")
        self.assertIsInstance(r_val, float)
        self.assertGreaterEqual(r_val, MIN_R)
        self.assertLessEqual(r_val, MAX_R)

    def test_r_is_clamped_to_plausible_range(self) -> None:
        low_r = r_coefficient(gender="unknown", age=150, weight=500, height=50, fat="high")
        high_r = r_coefficient(gender="unknown", age=1, weight=1, height=300, fat="low")
        self.assertGreaterEqual(low_r, MIN_R)
        self.assertLessEqual(low_r, MAX_R)
        self.assertGreaterEqual(high_r, MIN_R)
        self.assertLessEqual(high_r, MAX_R)

    def test_beta_is_clamped_to_plausible_range(self) -> None:
        low = estimate_beta(session_history=[-1.0, 0.0, 0.0001])
        high = estimate_beta(session_history=[1.0, 2.0, 3.0])
        self.assertGreaterEqual(low, MIN_BETA_PER_HOUR)
        self.assertLessEqual(low, MAX_BETA_PER_HOUR)
        self.assertGreaterEqual(high, MIN_BETA_PER_HOUR)
        self.assertLessEqual(high, MAX_BETA_PER_HOUR)

    def test_calculate_bac_range_is_ordered(self) -> None:
        result = calculate_bac_range(
            alc_g=42.0,
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.015,
            hours_elapsed=1.0,
        )
        self.assertLessEqual(result["low"], result["estimate"])
        self.assertLessEqual(result["estimate"], result["high"])

    def test_event_aware_bac_zero_before_first_drink(self) -> None:
        bac = event_aware_bac_at_time(
            [{"grams_alcohol": 14, "hours_from_session_start": 1.0}],
            t=0.5,
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.015,
        )
        self.assertEqual(bac, 0.0)

    def test_event_aware_bac_respects_drink_timing(self) -> None:
        first_only = event_aware_bac_at_time(
            [{"grams_alcohol": 14, "hours_from_session_start": 0.0}],
            t=1.0,
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.015,
        )
        with_late_drink = event_aware_bac_at_time(
            [
                {"grams_alcohol": 14, "hours_from_session_start": 0.0},
                {"grams_alcohol": 28, "hours_from_session_start": 2.0},
            ],
            t=1.0,
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.015,
        )
        self.assertAlmostEqual(first_only, with_late_drink, places=6)

    def test_event_aware_bac_differs_from_all_at_start_for_late_drink(self) -> None:
        event_aware = event_aware_bac_at_time(
            [
                {"grams_alcohol": 14, "hours_from_session_start": 0.0},
                {"grams_alcohol": 28, "hours_from_session_start": 2.0},
            ],
            t=1.0,
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.015,
        )
        all_at_start = calculate_bac(
            alc_g=28.0,
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.015,
            hours_elapsed=1.0,
        )
        self.assertLess(event_aware, all_at_start)

    def test_event_aware_curve_contains_sorted_nonnegative_points(self) -> None:
        result = generate_event_aware_bac_curve(
            [
                {"grams_alcohol": 14, "hours_from_session_start": 0.0},
                {"grams_alcohol": 14, "hours_from_session_start": 1.0},
            ],
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.015,
            current_time_hours=1.0,
        )
        curve = result["curve"]
        self.assertGreater(len(curve), 0)
        self.assertEqual(result["metadata"]["source"], "event_aware")
        self.assertEqual([p["hour"] for p in curve], sorted(p["hour"] for p in curve))
        self.assertTrue(all(p["estimate"] >= 0 for p in curve))

    def test_event_aware_curve_reports_peak_from_curve(self) -> None:
        result = generate_event_aware_bac_curve(
            [
                {"grams_alcohol": 14, "hours_from_session_start": 0.0},
                {"grams_alcohol": 28, "hours_from_session_start": 2.0},
            ],
            weight_kg=70.0,
            r=0.6,
            beta_per_hour=0.015,
            current_time_hours=1.0,
        )
        peak_from_points = max(point["estimate"] for point in result["curve"])
        self.assertAlmostEqual(result["peak_bac"], peak_from_points, places=6)
        self.assertEqual(result["peak_status"], "future")
        self.assertGreater(result["time_to_peak_hours"], 0)

    def test_food_intake_changes_event_aware_curve(self) -> None:
        events = [{"grams_alcohol": 14, "hours_from_session_start": 0.0}]
        no_food = event_aware_bac_at_time(events, 0.25, 70.0, 0.6, 0.015, food_intake="none")
        high_food = event_aware_bac_at_time(events, 0.25, 70.0, 0.6, 0.015, food_intake="high")
        self.assertLess(high_food, no_food)


if __name__ == "__main__":
    unittest.main()
