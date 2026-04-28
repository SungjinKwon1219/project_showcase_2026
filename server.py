"""Lightweight HTTP API for BAC prediction endpoints.

Run locally:
    python3 server.py
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from BACCalculator import calculate_bac_range, estimate_beta, r_coefficient


HOST = "0.0.0.0"
PORT = 8000


def _json_error(message: str, status: int = 400) -> tuple[dict[str, Any], int]:
    return {"error": {"message": message, "status": status}}, status


def _as_float(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")
    return float(value)


def _body_fat_bracket_from_percent(body_fat_percent: float) -> str:
    if body_fat_percent < 15:
        return "low"
    if body_fat_percent <= 25:
        return "mid"
    return "high"


def predict_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate request payload and return canonical prediction response."""
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    profile = payload.get("profile")
    session = payload.get("session")
    if not isinstance(profile, dict):
        raise ValueError("profile is required and must be an object.")
    if not isinstance(session, dict):
        raise ValueError("session is required and must be an object.")

    sex = profile.get("sex", "other")
    age_years = _as_float(profile.get("age_years"), "profile.age_years")
    height_cm = _as_float(profile.get("height_cm"), "profile.height_cm")
    weight_kg = _as_float(profile.get("weight_kg"), "profile.weight_kg")

    body_fat_bracket = profile.get("body_fat_bracket")
    body_fat_percent = profile.get("body_fat_percent")
    if body_fat_bracket is None and isinstance(body_fat_percent, (int, float)):
        body_fat_bracket = _body_fat_bracket_from_percent(float(body_fat_percent))

    standard_drinks = session.get("standard_drinks")
    grams_alcohol = session.get("grams_alcohol")
    hours_elapsed = _as_float(session.get("hours_elapsed"), "session.hours_elapsed")

    if grams_alcohol is None:
        if standard_drinks is None:
            raise ValueError("session.grams_alcohol or session.standard_drinks is required.")
        standard_drinks = _as_float(standard_drinks, "session.standard_drinks")
        if standard_drinks < 0:
            raise ValueError("session.standard_drinks cannot be negative.")
        grams_alcohol = standard_drinks * 14.0
    else:
        grams_alcohol = _as_float(grams_alcohol, "session.grams_alcohol")

    if age_years <= 0:
        raise ValueError("profile.age_years must be positive.")
    if height_cm <= 0:
        raise ValueError("profile.height_cm must be positive.")
    if weight_kg <= 0:
        raise ValueError("profile.weight_kg must be positive.")
    if grams_alcohol < 0:
        raise ValueError("session.grams_alcohol cannot be negative.")
    if hours_elapsed < 0:
        raise ValueError("session.hours_elapsed cannot be negative.")

    r = r_coefficient(
        gender=str(sex),
        age=age_years,
        weight=weight_kg,
        height=height_cm,
        fat=body_fat_bracket,
    )
    beta_per_hour = estimate_beta()
    bac = calculate_bac_range(
        alc_g=grams_alcohol,
        weight_kg=weight_kg,
        r=r,
        beta_per_hour=beta_per_hour,
        hours_elapsed=hours_elapsed,
    )

    return {
        "schema_version": 1,
        "units": {
            "bac": "display_decimal_0_08_means_0_08_percent",
            "beta_per_hour": "bac_display_units_per_hour",
            "weight": "kg",
            "height": "cm",
            "alcohol": "grams_ethanol",
            "time": "hours",
        },
        "model": {
            "name": "widmark-deterministic-v1",
            "r": round(r, 6),
            "beta_per_hour": round(beta_per_hour, 6),
        },
        "bac": {
            "low": round(float(bac["low"]), 6),
            "estimate": round(float(bac["estimate"]), 6),
            "high": round(float(bac["high"]), 6),
        },
        "meta": {
            "disclaimer": (
                "Estimate only; not legal or medical advice. "
                "Do not use this estimate to make driving decisions."
            )
        },
    }


class BACRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, body: dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body, status = _json_error("Request body must be valid JSON.", 400)
            self._send_json(body, status)
            return

        if self.path == "/r-coefficient":
            try:
                r = r_coefficient(
                    gender=payload.get("gender"),
                    age=_as_float(payload.get("age"), "age"),
                    weight=_as_float(payload.get("weight"), "weight"),
                    height=_as_float(payload.get("height"), "height"),
                    fat=payload.get("fat"),
                )
                self._send_json({"r": round(r, 6)}, 200)
            except ValueError as exc:
                body, status = _json_error(str(exc), 400)
                self._send_json(body, status)
            return

        if self.path == "/predict":
            try:
                response = predict_from_payload(payload)
                self._send_json(response, 200)
            except ValueError as exc:
                body, status = _json_error(str(exc), 400)
                self._send_json(body, status)
            return

        body, status = _json_error("Route not found.", 404)
        self._send_json(body, status)


def run_server() -> None:
    server = HTTPServer((HOST, PORT), BACRequestHandler)
    print(f"BAC API listening at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
