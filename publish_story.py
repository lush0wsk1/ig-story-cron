#!/usr/bin/env python3
"""Instagram Story auto-publisher — publish preset images as Stories.

Targets your OWN Instagram Business account through the official Graph API
(Content Publishing API, media_type=STORIES). Designed to run from a cron /
GitHub Actions schedule every PUBLISH_INTERVAL_H hours.

Highlights
----------
* Deterministic rotation (no state file needed): picks the image for the
  current 3-hour time slot, so stateless CI runs stay consistent.
* Automatic token refresh: every run exchanges the stored token for a fresh
  long-lived (60-day) token so the job never dies from expiry.
* Auto-discovers your Instagram Business Account ID from the linked Facebook
  Page when IG_BUSINESS_ACCOUNT_ID is not set.

Usage
-----
    python publish_story.py --dry-run        # only show what would happen
    python publish_story.py --now            # force publish the current slot
    python publish_story.py --url https://.../x.jpg   # publish a specific URL
    python publish_story.py --refresh-only   # just refresh the token (chore)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = "https://graph.facebook.com/v26.0"
HERE = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")
except ImportError:
    pass


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def env(name: str, required: bool = False, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        sys.exit(f"[ERROR] Missing required config: {name}")
    return value


def _env_path() -> Path:
    return HERE / ".env"


def api(method: str, url: str, *, timeout: int = 30, **kw) -> requests.Response:
    """HTTP helper that NEVER leaks URLs/tokens in errors.

    Git Hub logs show tracebacks, so a requests.raise_for_status() would leak
    the access_token (which is part of the URL) if the repo is public. This
    helper only raises the API's error *message*.
    """
    resp = requests.request(method, url, timeout=timeout, **kw)
    if not resp.ok:
        try:
            body = resp.json().get("error", {})
            detail = body.get("message", "") or resp.text[:300]
        except Exception:
            detail = resp.text[:300]
        raise RuntimeError(f"[API {resp.status_code}] {detail}")
    return resp


def write_env(key: str, value: str) -> None:
    """(Re)write one KEY=VALUE line into .env so refreshed tokens persist."""
    path = _env_path()
    lines = []
    if path.exists():
        lines = path.read_text().splitlines()
    hit = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            hit = True
    if not hit:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# token handling
# --------------------------------------------------------------------------
def refresh_access_token() -> str:
    """Exchange/refresh the stored token into a fresh long-lived (60-day) token.

    On GitHub Actions we intentionally SKIP the refresh so the value used is
    always the repository secret (GitHub masks secrets in logs). The secret is
    updated manually every ~50 days.
    """
    token = env("IG_USER_TOKEN", required=True)
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("[ok] running on GitHub Actions — using secret token as-is (no refresh)")
        return token
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": env("APP_ID", required=True),
        "client_secret": env("APP_SECRET", required=True),
        "fb_exchange_token": token,
    }
    try:
        resp = api("GET", f"{BASE}/oauth/access_token", params=params, timeout=30)
        new_token = resp.json().get("access_token", "").strip()
        if new_token:
            write_env("IG_USER_TOKEN", new_token)
            print("[ok] token refreshed -> long-lived token stored in .env")
            return new_token
    except RuntimeError as exc:
        print(f"[warn] token refresh skipped ({exc}); using stored token", file=sys.stderr)
    return token


# --------------------------------------------------------------------------
# Instagram account id
# --------------------------------------------------------------------------
def discover_ig_account_id(token: str) -> str:
    """Find the Instagram Business Account ID from the linked Facebook Page."""
    existing = env("IG_BUSINESS_ACCOUNT_ID")
    if existing:
        return existing

    # Preferred: ask the linked Page directly when PAGE_ID is known
    # (/me/accounts can return empty for pages owned via a Business Portfolio).
    page_id = env("PAGE_ID")
    if page_id:
        resp = api(
            "GET",
            f"{BASE}/{page_id}",
            params={"fields": "id,name,instagram_business_account", "access_token": token},
        )
        page = resp.json()
        ig = page.get("instagram_business_account") or {}
        if ig.get("id"):
            ig_id = ig["id"]
            write_env("IG_BUSINESS_ACCOUNT_ID", ig_id)
            print(f"[ok] IG account discovered from page {page_id}: {ig_id}")
            return ig_id
        sys.exit(
            "[ERROR] The page exists but Instagram is not linked to it.\n"
            "  - Relink it via IG app -> Account Center -> Linked accounts -> "
            "link to the PAGE (not the profile), then retry."
        )

    resp = api(
        "GET",
        f"{BASE}/me/accounts",
        params={
            "fields": "id,name,instagram_business_account{id}",
            "access_token": token,
        },
    )
    pages = resp.json().get("data", [])
    for page in pages:
        ig = page.get("instagram_business_account") or {}
        if ig.get("id"):
            ig_id = ig["id"]
            write_env("IG_BUSINESS_ACCOUNT_ID", ig_id)
            print(f"[ok] Instagram Business Account ID: {ig_id} (page: {page.get('name')})")
            return ig_id

    sys.exit(
        "[ERROR] No Instagram business account found under this token.\n"
        "  - Is the IG account type 'Business' and linked to a Facebook Page?\n"
        "  - Does the token include pages_read_engagement / pages_show_list?\n"
        "  - Set PAGE_ID in .env to skip uncertain discovery."
    )


# --------------------------------------------------------------------------
# rotation
# --------------------------------------------------------------------------
def load_entries() -> list[tuple[str, str | None]]:
    """Load (filename, caption) pairs from stories/playlist.json."""
    playlist_path = HERE / "stories" / "playlist.json"
    if not playlist_path.exists():
        sys.exit("[ERROR] stories/playlist.json not found — create it with your image names.")
    playlist = json.loads(playlist_path.read_text())

    entries: list[tuple[str, str | None]] = []
    for item in playlist:
        if isinstance(item, dict):
            name = (item.get("file") or "").strip()
            if name:
                entries.append((name, item.get("caption")))
        elif isinstance(item, str):
            name = item.strip()
            if name:
                entries.append((name, None))
    if not entries:
        sys.exit("[ERROR] stories/playlist.json is empty — add your image file names.")
    return entries


def image_url_for(filename: str) -> str:
    base = env("PUBLIC_BASE_URL")
    if not base:
        sys.exit(
            "[ERROR] PUBLIC_BASE_URL is not set.\n"
            "  The Instagram API needs a PUBLIC url for every image (it fetches the file itself).\n"
            "  Example with a public GitHub repo + jsDelivr CDN:\n"
            "    PUBLIC_BASE_URL=https://cdn.jsdelivr.net/gh/YOUR_GH_USER/YOUR_REPO@main/stories"
        )
    return f"{base.rstrip('/')}/{filename}"


def pick_image() -> tuple[str, str, str | None]:
    """Deterministically pick the (image, caption) for this time slot.

    playlist.json entries can be:
      {"file": "a.jpg", "caption": "texto"}  -> image + publication text
      "b.jpg"                                -> image without text
    """
    entries = load_entries()
    interval_h = int(env("PUBLISH_INTERVAL_H", default="3"))
    slot = int(time.time()) // (interval_h * 3600)
    filename, caption = entries[slot % len(entries)]
    return filename, image_url_for(filename), caption


# --------------------------------------------------------------------------
# publishing (two-step container flow)
# --------------------------------------------------------------------------
def create_container(
    ig_id: str,
    image_url: str,
    token: str,
    media_type: str | None = None,
    caption: str | None = None,
) -> str:
    params = {"image_url": image_url, "access_token": token}
    if media_type:
        params["media_type"] = media_type
    if caption:
        params["caption"] = caption
    resp = api("POST", f"{BASE}/{ig_id}/media", params=params)
    return resp.json()["id"]


def wait_until_ready(container_id: str, token: str, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = api(
            "GET",
            f"{BASE}/{container_id}",
            params={"fields": "status_code", "access_token": token},
        )
        status = resp.json().get("status_code", "")
        print(f"[...] container status: {status}")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            return False
        time.sleep(5)
    return False


def publish_container(ig_id: str, container_id: str, token: str) -> str:
    params = {"creation_id": container_id, "access_token": token}
    resp = api("POST", f"{BASE}/{ig_id}/media_publish", params=params)
    return resp.json().get("id", "")


# --------------------------------------------------------------------------
# reading comments
# --------------------------------------------------------------------------
def read_comments(token: str, ig_id: str, media_limit: int = 5) -> None:
    """List the most recent media and read their comments (requires the
    instagram_business_manage_comments permission on the token)."""
    resp = api(
        "GET",
        f"{BASE}/{ig_id}/media",
        params={
            "fields": "id,caption,timestamp,media_type",
            "limit": str(media_limit),
            "access_token": token,
        },
    )
    media = resp.json().get("data", [])
    if not media:
        print("[!] No media found on this account.")
        return

    for item in media:
        print(f"\n[media] {item['id']}  [{item.get('media_type')}]  {item.get('timestamp', '')}")
        caption = (item.get("caption") or "").strip()
        if caption:
            print(f"    caption: {caption[:150]}")
        comments_resp = requests.get(
            f"{BASE}/{item['id']}/comments",
            params={
                "fields": "id,text,username,timestamp",
                "limit": "50",
                "access_token": token,
            },
            timeout=30,
        )
        if not comments_resp.ok:
            print(
                f"    💬 (no comments or missing permission: "
                f"{comments_resp.json().get('error', {}).get('message', '')})"
            )
            continue
        comments = comments_resp.json().get("data", [])
        if not comments:
            print("    💬 (sin comentarios)")
        for comment in comments:
            print(f"    💬 @{comment.get('username')}: {comment.get('text')}  ({comment.get('timestamp')})")


# --------------------------------------------------------------------------
# auto-reply (AI replies) — FASE 1: solo borradores, nunca publica
# --------------------------------------------------------------------------
REPLIED_STATE = HERE / "replied.json"
DRAFTS_DIR = HERE / "drafts"


def _load_replied() -> list[str]:
    if REPLIED_STATE.exists():
        try:
            return [line.strip() for line in REPLIED_STATE.read_text().splitlines() if line.strip()]
        except Exception:
            pass
    return []


def _mark_replied(comment_id: str) -> None:
    seen = _load_replied()
    if comment_id not in seen:
        seen.append(comment_id)
        REPLIED_STATE.write_text("\n".join(seen) + "\n")


def fetch_recent_comments(token: str, ig_id: str, media_limit: int = 10) -> list[dict]:
    """Collect comments from recent posts (account's own media only)."""
    out: list[dict] = []
    resp = api(
        "GET",
        f"{BASE}/{ig_id}/media",
        params={"fields": "id,media_type", "limit": str(media_limit), "access_token": token},
    )
    for m in resp.json().get("data", []):
        cr = requests.get(
            f"{BASE}/{m['id']}/comments",
            params={"fields": "id,text,username,timestamp", "limit": "50", "access_token": token},
            timeout=30,
        )
        if not cr.ok:
            continue
        for c in cr.json().get("data", []):
            c["media_id"] = m["id"]
            out.append(c)
    return out


DEFAULT_VOICE = (
    "Marca: 'Lopc Pro Spa' — tienda de olivos artificiales premium (decoración mediterránea). "
    "Tono cercano, profesional y optimista, respondiendo en el idioma del comentario."
)


def ask_opencode(comment: dict, *, voice: str, model: str = "") -> str:
    """Call `opencode run` with the comment and return the proposed reply."""
    prompt = (
        voice
        + "\n"
        + "Un seguidor ha comentado en Instagram. Redacta UNA respuesta breve (max 480 caracteres). "
        + "Si el comentario es spam, insulto o no merece respuesta, responde exactamente: SKIP\n"
        + "\nCOMENTARIO por @"
        + comment.get("username", "?")
        + ": "
        + str(comment.get("text", ""))
        + "\n\nRESPUESTA:"
    )
    cmd = ["opencode", "run"]
    if model:
        cmd += ["--model", model]
    cmd += [prompt]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise RuntimeError("opencode no está instalado o no está en el PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError("opencode superó el tiempo límite (120s)")
    if proc.returncode != 0:
        raise RuntimeError(f"opencode falló (exit {proc.returncode}): {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def reply_draft(token: str, ig_id: str, *, publish: bool, model: str, voice: str) -> None:
    """Scan recent comments and (if not already processed) draft an AI reply.

    FASE 1 (default): writes drafts/<comment_id>.txt and never posts.
    FASE 2 (--publish-reply): posts the reply to Instagram on the same run.
    """
    DRAFTS_DIR.mkdir(exist_ok=True)
    seen = set(_load_replied())
    comments = fetch_recent_comments(token, ig_id)
    comments = [c for c in comments if c["id"] not in seen]
    if not comments:
        print("[info] sin comentarios nuevos que procesar.")
        return

    for c in comments:
        cid = c["id"]
        try:
            reply = ask_opencode(c, voice=voice, model=model)
        except RuntimeError as exc:
            print(f"[warn] @{c.get('username')}: {exc}")
            continue
        _mark_replied(cid)

        is_skip = reply.strip().upper() == "SKIP"
        if publish and not is_skip:
            message = reply.strip()[:480]
            r = api("POST", f"{BASE}/{cid}/replies", params={"message": message, "access_token": token})
            print(f"[OK] respondido a @{c.get('username')} (reply id {r.json().get('id')})")
        else:
            if is_skip:
                print(f"[skip] @{c.get('username')}: sin respuesta (SKIP)")
            draft_path = DRAFTS_DIR / f"{cid}.txt"
            draft_path.write_text(
                "@"
                + str(c.get("username", "?"))
                + " | "
                + str(c.get("timestamp", ""))
                + "\nCOM: "
                + str(c.get("text", ""))
                + "\nRESPUESTA PROPUESTA:\n"
                + reply.strip()[:480]
                + "\n"
            )
            print(f"[borrador] @{c.get('username')} -> {draft_path.name}")


# --------------------------------------------------------------------------
# AI writer: generate the caption with opencode (tags + memory + fallback)
# --------------------------------------------------------------------------
def load_images_index() -> dict:
    """images.json: { "file.jpg": { "desc": "...", "tags": [...] } }"""
    path = HERE / "images.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def load_last_captions(keep: int = 20) -> list[str]:
    path = HERE / "last_captions.json"
    if path.exists():
        try:
            items = json.loads(path.read_text())
            if isinstance(items, list):
                return items[-keep:]
        except Exception:
            pass
    return []


def save_last_captions(caption: str, keep: int = 20) -> None:
    if not caption:
        return
    path = HERE / "last_captions.json"
    items = load_last_captions(keep)
    if caption not in items:
        items.append(caption)
        path.write_text(json.dumps(items[-keep:], ensure_ascii=False, indent=2))


def build_ai_prompt(filename: str, desc: str, tags: list[str], last: list[str]) -> str:
    voice = env("AI_BRAND_VOICE")
    if not voice:
        voice = (
            "Eres el community manager de 'Lopc Pro Spa', tienda de arboles artificiales "
            "de olivo premium (decoracion mediterranea). Escribes captions de Instagram "
            "para una cuenta de negocio con tono cercano, natural y optimista."
        )
    tags_str = ", ".join(tags) if tags else "(sin tags)"
    last_str = "; ".join(last[-5:]) if last else "ninguno"
    return (
        voice
        + "\n\nCRITERIOS: maximo 400 caracteres, en espanol, tono de persona real, "
        + "solo 1-3 hashtags al final.\n"
        + f"FOTO A PUBLICAR: {filename}\n"
        + f"Descripcion: {desc}\n"
        + f"Tags de la foto: {tags_str}\n\n"
        + "DATOS DEL PRODUCTO (usa solo estos, no inventes): sin riego ni sol, dura "
        + "5-8 anos, 160 cm, materiales ecologicos, hojas 'natural touch', tronco de "
        + "polietileno y acero galvanizado, apto interior/exteriores protegidos, "
        + "ideal bodas, oficinas y regalos.\n\n"
        + "INSTRUCCIONES:\n"
        + "1. Escribe un caption NUEVO usando como eje los tags de esta foto.\n"
        + "2. Varia la estructura: elige un gancho aleatorio (pregunta retorica, dato "
        + "curioso, emocion o mini-historia), desarrollo basado en los tags, y cierra "
        + "con un CTA rotando entre 'Escribenos por DM', 'Comenta cual te gusta' e "
        + f"'Ideal para {tags[0] if tags else 'decoracion'}'.\n"
        + f"3. NO repitas frases ni openings de estos captions anteriores: {last_str}\n"
        + "4. Devuelve SOLO el caption, sin comillas ni prefijos."
    )


def generate_caption(filename: str) -> str:
    """Call `opencode run` with the built prompt. Raises RuntimeError on any failure."""
    index = load_images_index().get(filename, {})
    desc = (index.get("desc") or "").strip() or filename
    tags = index.get("tags") or []
    prompt = build_ai_prompt(filename, desc, tags, load_last_captions())

    cmd = ["opencode", "run"]
    model = env("AI_MODEL")
    if model:
        cmd += ["--model", model]
    cmd += [prompt]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        raise RuntimeError("opencode no esta instalado o no esta en el PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError("opencode supero el limite (180s)")
    if proc.returncode != 0:
        raise RuntimeError(f"opencode fallo (exit {proc.returncode}): {proc.stderr.strip()[:200]}")
    text = proc.stdout.strip()
    if not text:
        raise RuntimeError("opencode devolvio una respuesta vacia")
    return text[:2200]


def fallback_caption(filename: str) -> str:
    index = load_images_index().get(filename, {})
    tags = index.get("tags") or []
    tag = tags[0] if tags else "decoracion mediterranea"
    return (
        "Nuestro olivo artificial de 160 cm: sin riego, sin sol, siempre verde. "
        f"Ideal para {tag}. Escribenos por DM. 🌿 #olivoartificial #decor"
    )


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Publish an Instagram Story.")
    parser.add_argument("--dry-run", action="store_true", help="only show what would be published")
    parser.add_argument("--url", help="override the image URL to publish")
    parser.add_argument("--image", help="publish a specific file from stories/playlist.json (uses its caption)")
    parser.add_argument("--feed", action="store_true", help="publish as a feed post (grid) instead of a Story")
    parser.add_argument("--caption", help="caption text (feed posts)")
    parser.add_argument("--ai-caption", action="store_true", help="generate the caption with opencode (AI writer)")
    parser.add_argument("--ai-gen-only", action="store_true", help="generate the caption and exit (no publish)")
    parser.add_argument("--refresh-only", action="store_true", help="only refresh the token and exit")
    parser.add_argument("--comments", action="store_true", help="read comments from recent posts and exit")
    args = parser.parse_args()

    # Allow CI (GitHub Actions) to drive the run via environment variables.
    if not args.image and env("IG_POST_IMAGE"):
        args.image = env("IG_POST_IMAGE")
    if not args.url and env("IG_POST_URL"):
        args.url = env("IG_POST_URL")
    if not args.caption and env("IG_POST_CAPTION"):
        args.caption = env("IG_POST_CAPTION")
    is_feed = args.feed or env("IG_POST_MODE").lower() == "feed"

    token = refresh_access_token()
    if args.refresh_only:
        print("[ok] token is now valid for the next 60 days")
        return

    ig_id = discover_ig_account_id(token)
    if args.comments:
        read_comments(token, ig_id)
        return

    if args.image:
        entries = load_entries()
        match = next((e for e in entries if e[0] == args.image), None)
        if match is None:
            sys.exit(
                f"[ERROR] '{args.image}' is not in stories/playlist.json.\n"
                f"  Available images: {', '.join(e[0] for e in entries)}"
            )
        filename, picked_caption = match
        url = image_url_for(filename)
    elif args.url:
        filename = args.url
        url = args.url
        picked_caption = None
    else:
        filename, url, picked_caption = pick_image()

    ig_id = discover_ig_account_id(token)

    kind = "feed post" if is_feed else "Story"
    media_type = None if is_feed else "STORIES"
    caption = args.caption or picked_caption

    ai_used = False
    if args.ai_caption and is_feed and not args.caption:
        try:
            caption = generate_caption(filename)
            print("[IA] caption generado con opencode")
            ai_used = True
        except RuntimeError as exc:
            print(f"[warn] opencode: {exc}; usare caption de respaldo")
            caption = fallback_caption(filename)

    if args.ai_gen_only:
        print("CAPTION GENERADO:")
        print(caption)
        return

    if args.dry_run:
        print(f"[dry-run] would publish '{filename}' as a {kind} on IG account {ig_id}")
        print(f"[dry-run] image_url={url}")
        if caption:
            print(f"[dry-run] caption={caption}")
        if caption and not is_feed:
            print("[i] note: stories don't display captions — the text is ignored for stories.")
        return

    if caption and not is_feed:
        print("[i] note: stories don't display captions; playlist caption ignored.")

    print(f"[+] publishing {filename} -> {kind} on IG account {ig_id}")
    container_id = create_container(
        ig_id,
        url,
        token,
        media_type=media_type,
        caption=caption if is_feed else None,
    )
    if not wait_until_ready(container_id, token):
        sys.exit("[ERROR] container never became ready — check the image URL / format (JPG).")
    post_id = publish_container(ig_id, container_id, token)
    if is_feed and ai_used and caption:
        save_last_captions(caption)
    print(f"[OK] {kind} published! (post id: {post_id})")


if __name__ == "__main__":
    main()