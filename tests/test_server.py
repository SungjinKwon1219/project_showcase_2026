import unittest

from server import predict_from_payload


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
            },
            "session": {
                "standard_drinks": 3,
                "grams_alcohol": 42.0,
                "hours_elapsed": 2.0,
            },
        }

    def test_predict_returns_expected_shape(self):
        result = predict_from_payload(self._valid_payload())
        self.assertEqual(result["schema_version"], 1)
        self.assertIn("units", result)
        self.assertIn("model", result)
        self.assertIn("bac", result)
        self.assertIn("meta", result)

    def test_predict_rejects_negative_weight(self):
        payload = self._valid_payload()
        payload["profile"]["weight_kg"] = -1
        with self.assertRaises(ValueError):
            predict_from_payload(payload)

    def test_predict_rejects_negative_alcohol(self):
        payload = self._valid_payload()
        payload["session"]["grams_alcohol"] = -0.1
        with self.assertRaises(ValueError):
            predict_from_payload(payload)

    def test_predict_bac_is_ordered(self):
        result = predict_from_payload(self._valid_payload())
        low = result["bac"]["low"]
        est = result["bac"]["estimate"]
        high = result["bac"]["high"]
        self.assertLessEqual(low, est)
        self.assertLessEqual(est, high)


if __name__ == "__main__":
    unittest.main()
