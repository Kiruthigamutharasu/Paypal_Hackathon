"""Refresh the PayPal sandbox token used by the PayPal AI Toolkit in Claude Code.

Usage:  python scripts/paypal_token.py
Reads PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET / PAYPAL_BASE_URL from .env and writes
PAYPAL_SANDBOX_ACCESS_TOKEN into ~/.claude/settings.json ("env" block) only.
Tokens expire after ~9 hours: rerun on 401 errors, then restart Claude Code.

This is a developer tool. The StayCovered app itself fetches and refreshes its own
token at runtime from the client ID and secret; it never reads this token.
"""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
SETTINGS = Path.home() / ".claude" / "settings.json"


def read_env() -> dict:
    env = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def get_token(base: str, cid: str, secret: str) -> dict:
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        f"{base}/v1/oauth2/token",
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def write_claude_settings(token: str) -> None:
    data = {}
    if SETTINGS.exists():
        raw = SETTINGS.read_text(encoding="utf-8").strip()
        data = json.loads(raw) if raw else {}
        SETTINGS.with_suffix(".json.bak").write_text(raw, encoding="utf-8")
    data.setdefault("env", {})["PAYPAL_SANDBOX_ACCESS_TOKEN"] = token
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> None:
    env = read_env()
    cid, secret = env.get("PAYPAL_CLIENT_ID"), env.get("PAYPAL_CLIENT_SECRET")
    base = env.get("PAYPAL_BASE_URL") or "https://api-m.sandbox.paypal.com"
    if not cid or not secret:
        raise SystemExit("Fill PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env first.")
    try:
        resp = get_token(base, cid, secret)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"PayPal rejected the credentials ({e.code}): {e.read().decode()[:300]}")
    write_claude_settings(resp["access_token"])
    hours = resp.get("expires_in", 0) / 3600
    print(f"OK - token saved to {SETTINGS} (valid ~{hours:.1f}h).")
    print("Now fully restart Claude Code / reload the VS Code window.")


if __name__ == "__main__":
    main()
