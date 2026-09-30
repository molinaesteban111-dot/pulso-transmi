"""Vercel serverless endpoint for personal competition monitoring."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://pulso-transmi.72-60-245-2.sslip.io"
DEFAULT_DISPLAY_NAME = "Juan Esteban Molina"
DEFAULT_SUPABASE_URL = "https://bppwpnpidjffhzojquml.supabase.co"
# Publishable keys are intentionally safe for public clients. Database access
# is restricted to the dashboard_monitoring() RPC below.
DEFAULT_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_UxOmiZjE52o7FcBegMt2Uw_ab_61Z4w"


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
    """Build the public payload for one participant."""
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


def supabase_headers(api_key: str) -> dict[str, str]:
    """Build REST headers for modern opaque keys or legacy JWT keys."""
    headers = {"apikey": api_key, "Accept": "application/json"}
    if api_key.startswith("eyJ") and api_key.count(".") == 2:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def merge_current_drift(history: list[dict], metrics: dict | None) -> list[dict]:
    """Append the live drift when its timestamp is not persisted yet."""
    points = list(reversed(history))
    if not metrics or metrics.get("drift_percentage_points") is None:
        return points
    current = {
        "accuracy": metrics.get("accuracy"),
        "drift": metrics.get("drift_percentage_points"),
        "calculated_at": metrics.get("calculated_at"),
    }
    if not points or points[-1].get("calculated_at") != current["calculated_at"]:
        points.append(current)
    return points[-24:]


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

        warnings = []
        try:
            rolling_24h = self._leaderboard(base_url, api_key, "rolling_24h")
        except Exception as exc:
            print(json.dumps({"event": "rolling_leaderboard_failed", "error": str(exc)}))
            rolling_24h = None
            warnings.append("El drift actual no está disponible temporalmente.")

        payload = personal_metrics(cumulative, rolling_24h, display_name)
        monitoring = self._supabase_monitoring()
        payload["runs"] = monitoring["runs"]
        payload["drift_history"] = merge_current_drift(
            monitoring["drift_history"], payload.get("metrics")
        )
        if monitoring.get("warning"):
            warnings.append(monitoring["warning"])
        if warnings:
            payload["warning"] = " ".join(warnings)
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

    def _supabase_monitoring(self) -> dict:
        base_url = os.environ.get("SUPABASE_URL", DEFAULT_SUPABASE_URL).rstrip("/")
        publishable_key = os.environ.get(
            "SUPABASE_PUBLISHABLE_KEY", DEFAULT_SUPABASE_PUBLISHABLE_KEY
        )
        result = {"runs": [], "drift_history": []}
        try:
            payload = self._get_json(
                f"{base_url}/rest/v1/rpc/dashboard_monitoring",
                supabase_headers(publishable_key),
            )
            result["runs"] = payload.get("runs", [])
            result["drift_history"] = payload.get("drift_history", [])
        except Exception as exc:
            print(json.dumps({"event": "supabase_monitoring_failed", "error": str(exc)}))
            result["warning"] = "El historial no está disponible temporalmente."
        return result

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
