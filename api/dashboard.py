"""Serverless endpoint for the Pulso TransMi monitoring dashboard."""

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def handler(request):
    base_url = os.environ.get("PULSO_API_URL", "https://pulso-transmi.72-60-245-2.sslip.io").rstrip("/")
    api_key = os.environ.get("PULSO_API_KEY")
    if not api_key:
        return {"statusCode": 500, "body": json.dumps({"error": "PULSO_API_KEY no configurada"})}

    url = f"{base_url}/v1/leaderboard?{urlencode({'window': 'cumulative'})}"
    req = Request(url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", "Cache-Control": "s-maxage=300"},
            "body": json.dumps(payload, ensure_ascii=False),
        }
    except Exception as exc:
        return {"statusCode": 502, "body": json.dumps({"error": str(exc)})}
