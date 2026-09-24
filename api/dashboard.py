"""Vercel serverless endpoint for the Pulso TransMi leaderboard."""

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base_url = os.environ.get(
            "PULSO_API_URL", "https://pulso-transmi.72-60-245-2.sslip.io"
        ).rstrip("/")
        api_key = os.environ.get("PULSO_API_KEY")
        if not api_key:
            self._json(500, {"error": "PULSO_API_KEY no configurada"})
            return

        try:
            payload = self._get_json(
                f"{base_url}/v1/leaderboard?{urlencode({'window': 'cumulative'})}",
                {"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            )
            payload["monitoring"] = self._supabase_monitoring()
            self._json(200, payload, cache_control="s-maxage=300")
        except Exception as exc:
            self._json(502, {"error": str(exc)})

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

    def _supabase_monitoring(self):
        base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not base_url or not service_key:
            return {"configured": False}
        headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
        result = {"configured": True}
        queries = {
            "submissions": "select=external_submission_id,cycle_id,prediction_count,status,submitted_at&order=submitted_at.desc&limit=10",
            "model": "select=version_name,algorithm,validation_accuracy,status,created_at&status=eq.champion&order=created_at.desc&limit=1",
            "runs": "select=run_type,status,started_at,finished_at,error_message&order=started_at.desc&limit=10",
        }
        tables = {"submissions": "submissions", "model": "model_versions", "runs": "pipeline_runs"}
        for name, query in queries.items():
            try:
                result[name] = self._get_json(f"{base_url}/rest/v1/{tables[name]}?{query}", headers)
            except Exception:
                result[name] = []
        return result
