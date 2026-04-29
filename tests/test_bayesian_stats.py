import unittest

from BayesianStats import estimate_personalized_beta


class BayesianStatsTests(unittest.TestCase):
    def test_zero_observed_returns_population_source(self):
        result = estimate_personalized_beta([])
        self.assertEqual(result["source"], "population")
        self.assertEqual(result["sessions_used"], 0)
        self.assertEqual(result["beta"], 0.015)
        self.assertEqual(result["personal_weight"], 0.0)
        self.assertEqual(result["population_weight"], 1.0)
        self.assertIsNone(result["posterior_beta"])
        self.assertIsNone(result["observed_mean"])
        self.assertIsNone(result["observed_sd"])

    def test_one_observed_returns_single_session_average(self):
        result = estimate_personalized_beta([0.011])
        self.assertEqual(result["source"], "single_session_average")
        self.assertEqual(result["sessions_used"], 1)
        self.assertAlmostEqual(result["beta"], 0.013)
        self.assertEqual(result["personal_weight"], 0.5)
        self.assertEqual(result["population_weight"], 0.5)
        self.assertEqual(result["observed_mean"], 0.011)
        self.assertIsNone(result["observed_sd"])

    def test_two_or_more_observed_returns_bayesian_personalized(self):
        result = estimate_personalized_beta([0.011, 0.012, 0.013])
        self.assertEqual(result["source"], "bayesian_personalized")
        self.assertEqual(result["sessions_used"], 3)
        self.assertIsNotNone(result["posterior_beta"])
        self.assertIsNotNone(result["observed_mean"])
        self.assertIsNotNone(result["observed_sd"])

    def test_identical_observed_betas_do_not_divide_by_zero(self):
        result = estimate_personalized_beta([0.012, 0.012, 0.012])
        self.assertEqual(result["source"], "bayesian_personalized")
        self.assertEqual(result["observed_sd"], 0.0)
        self.assertIn("observed_sd_below_minimum_for_posterior", result["warnings"])
        self.assertGreaterEqual(result["beta"], result["min_beta"])
        self.assertLessEqual(result["beta"], result["max_beta"])

    def test_invalid_observed_values_are_excluded(self):
        result = estimate_personalized_beta([0.012, "0.013", "bad", None, float("nan"), True])
        self.assertEqual(result["sessions_used"], 2)
        self.assertEqual(result["sessions_excluded"], 4)
        self.assertEqual(result["source"], "bayesian_personalized")

    def test_out_of_range_observed_values_are_excluded(self):
        result = estimate_personalized_beta([0.012, 0.004, 0.031, -1, 0])
        self.assertEqual(result["sessions_used"], 1)
        self.assertEqual(result["sessions_excluded"], 4)
        self.assertEqual(result["source"], "single_session_average")

    def test_metadata_counts_are_correct(self):
        result = estimate_personalized_beta([0.011, 0.012, 0.013, 0.1, "nope"])
        self.assertEqual(result["sessions_used"], 3)
        self.assertEqual(result["sessions_excluded"], 2)
        self.assertEqual(result["population_blend_weight"], 0.10)
        self.assertAlmostEqual(result["personal_weight"], 0.90)
        self.assertAlmostEqual(result["population_weight"], 0.10)

    def test_result_beta_is_clamped_within_min_max(self):
        result = estimate_personalized_beta([], population_beta=0.2)
        self.assertEqual(result["beta"], result["max_beta"])
        self.assertGreaterEqual(result["beta"], result["min_beta"])
        self.assertLessEqual(result["beta"], result["max_beta"])


if __name__ == "__main__":
    unittest.main()
