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

        url = f"{base_url}/v1/leaderboard?{urlencode({'window': 'cumulative'})}"
        request = Request(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
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
