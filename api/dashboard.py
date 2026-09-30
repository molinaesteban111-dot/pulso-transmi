"""Vercel serverless endpoint for the student's personal competition metrics."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://pulso-transmi.72-60-245-2.sslip.io"
DEFAULT_DISPLAY_NAME = "Juan Esteban Molina"


def _participant(board: dict, display_name: str) -> dict | None:
    """Return one participant without exposing the rest of the leaderboard."""
    return next(
        (row for row in board.get("data", []) if row.get("display_name") == display_name),
        None,
    )


def personal_metrics(
    cumulative: dict,
    rolling_24h: dict | None,
    display_name: str = DEFAULT_DISPLAY_NAME,
) -> dict:
    """Build the public payload for one participant.

    Performance drift is measured in percentage points as the rolling 24-hour
    accuracy minus the cumulative accuracy. A negative value means recent
    performance is below the cumulative result.
    """
    current = _participant(cumulative, display_name)
    recent = _participant(rolling_24h or {}, display_name)
    if current is None:
        return {
            "participant": display_name,
            "metrics": None,
            "message": "Aún no hay métricas oficiales para este participante.",
        }

    cumulative_accuracy = float(current["accuracy"])
    recent_accuracy = float(recent["accuracy"]) if recent else None
    drift = (
        round(recent_accuracy - cumulative_accuracy, 6)
        if recent_accuracy is not None
        else None
    )
    return {
        "participant": display_name,
        "metrics": {
            "position": current.get("rank"),
            "accuracy": cumulative_accuracy,
            "drift_percentage_points": drift,
            "rolling_24h_accuracy": recent_accuracy,
            "calculated_at": current.get("calculated_at"),
        },
        "definition": {
            "drift": "accuracy de las últimas 24 horas menos accuracy acumulada",
        },
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base_url = os.environ.get("PULSO_API_URL", DEFAULT_API_URL).rstrip("/")
        api_key = os.environ.get("PULSO_API_KEY")
        display_name = os.environ.get("PULSO_DISPLAY_NAME", DEFAULT_DISPLAY_NAME)
        if not api_key:
            self._json(500, {"error": "PULSO_API_KEY no configurada"})
            return

        try:
            cumulative = self._leaderboard(base_url, api_key, "cumulative")
        except Exception as exc:
            print(json.dumps({"event": "cumulative_leaderboard_failed", "error": str(exc)}))
            self._json(502, {"error": "El leaderboard oficial no está disponible."})
            return

        warning = None
        try:
            rolling_24h = self._leaderboard(base_url, api_key, "rolling_24h")
        except Exception as exc:
            print(json.dumps({"event": "rolling_leaderboard_failed", "error": str(exc)}))
            rolling_24h = None
            warning = "El drift no está disponible temporalmente."

        payload = personal_metrics(cumulative, rolling_24h, display_name)
        if warning:
            payload["warning"] = warning
        self._json(
            200,
            payload,
            cache_control="s-maxage=15, stale-while-revalidate=15",
        )

    def _leaderboard(self, base_url: str, api_key: str, window: str) -> dict:
        return self._get_json(
            f"{base_url}/v1/leaderboard?{urlencode({'window': window})}",
            {"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )

    def _json(self, status, payload, cache_control=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _get_json(url, headers):
        request = Request(url, headers=headers)
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
