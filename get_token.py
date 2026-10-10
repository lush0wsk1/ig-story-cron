#!/usr/bin/env python3
"""One-time helper: mint a Facebook USER access token with the IG permissions.

Why this exists: the Graph API Explorer's permission picker and the
redirect-to-explorer OAuth dance are both unreliable on some accounts. This
uses the standard OAuth Authorization Code flow with a localhost redirect,
which Meta accepts, and stores a *short-lived* user token in .env.

After it finishes, run:  python publish_story.py --refresh-only
to convert it into a long-lived (60-day) token.

Usage:
    python get_token.py

Prerequisite: in the app dashboard -> Facebook Login -> Settings, add
   http://localhost:9876/callback
to "Valid OAuth Redirect URIs", and the "Facebook Login" product must be added.
"""
from __future__ import annotations

import http.server
import os
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
except ImportError:
    pass

PORT = 9876
REDIRECT = f"http://localhost:{PORT}/callback"
SCOPE = os.getenv("IG_SCOPES") or (
    "instagram_basic,"
    "instagram_content_publish,"
    "pages_read_engagement,"
    "pages_show_list"
)

APP_ID = os.getenv("APP_ID", "").strip()
APP_SECRET = os.getenv("APP_SECRET", "").strip()

received: dict = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        received["error"] = qs.get("error", [None])[0]
        received["code"] = qs.get("code", [None])[0]
        if received["error"]:
            body = f"Error de autorizacion: {received['error']}".encode()
        else:
            body = b"OK - token capturado, ya puedes cerrar esta pestana."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *args):  # silence
        pass


def write_env(key: str, value: str) -> None:
    path = HERE / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    hit = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            hit = True
    if not hit:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    if not APP_ID or not APP_SECRET:
        print("[ERROR] APP_ID and APP_SECRET must be set in .env first.")
        return

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    auth_url = "https://www.facebook.com/v26.0/dialog/oauth?" + urllib.parse.urlencode(
        {
            "client_id": APP_ID,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": SCOPE,
        }
    )
    print("1) Abre esta URL en tu navegador y acepta los permisos:")
    print("\n   " + auth_url + "\n")
    print("Esperando respuesta de Facebook... (se abre sola si tu navegador lo permite)")
    webbrowser.open(auth_url)
    server.serve_forever()

    if received.get("error"):
        print(f"[ERROR] Autorizacion fallida: {received['error']}")
        return
    code = received.get("code")
    if not code:
        print("[ERROR] No se recibio code. Revisa 'Valid OAuth Redirect URIs' en Facebook Login.")
        return

    resp = requests.get(
        "https://graph.facebook.com/v26.0/oauth/access_token",
        params={
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "redirect_uri": REDIRECT,
            "code": code,
        },
        timeout=30,
    )
    if not resp.ok:
        # Never echo the full URL here: it contains client_secret.
        try:
            detail = resp.json().get("error", {}).get("message", "") or resp.text[:300]
        except Exception:
            detail = resp.text[:300]
        print(f"[ERROR] el canje del codigo fallo (HTTP {resp.status_code}): {detail}")
        return
    token = resp.json()["access_token"]

    write_env("IG_USER_TOKEN", token)
    print("\n[OK] Token guardado en .env (corto plazo).")
    print("Siguiente paso:  python publish_story.py --refresh-only")
    print("para convertirlo en token largo (60 dias).")


if __name__ == "__main__":
    main()