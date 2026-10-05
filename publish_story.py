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

    Tolerant on purpose: System-user tokens (recommended) don't need
    refreshing and may reject the exchange call — we just keep using them.
    """
    token = env("IG_USER_TOKEN", required=True)
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": env("APP_ID", required=True),
        "client_secret": env("APP_SECRET", required=True),
        "fb_exchange_token": token,
    }
    try:
        resp = requests.get(f"{BASE}/oauth/access_token", params=params, timeout=30)
        resp.raise_for_status()
        new_token = resp.json().get("access_token", "").strip()
        if new_token:
            write_env("IG_USER_TOKEN", new_token)
            print("[ok] token refreshed -> long-lived token stored in .env")
            return new_token
    except requests.RequestException as exc:
        print(f"[warn] token refresh not needed/skipped ({exc}); using stored token", file=sys.stderr)
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
        resp = requests.get(
            f"{BASE}/{page_id}",
            params={"fields": "id,name,instagram_business_account", "access_token": token},
            timeout=30,
        )
        resp.raise_for_status()
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

    resp = requests.get(
        f"{BASE}/me/accounts",
        params={
            "fields": "id,name,instagram_business_account{id}",
            "access_token": token,
        },
        timeout=30,
    )
    resp.raise_for_status()
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
    resp = requests.post(f"{BASE}/{ig_id}/media", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def wait_until_ready(container_id: str, token: str, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{BASE}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        )
        resp.raise_for_status()
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
    resp = requests.post(f"{BASE}/{ig_id}/media_publish", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("id", "")


# --------------------------------------------------------------------------
# reading comments
# --------------------------------------------------------------------------
def read_comments(token: str, ig_id: str, media_limit: int = 5) -> None:
    """List the most recent media and read their comments (requires the
    instagram_business_manage_comments permission on the token)."""
    resp = requests.get(
        f"{BASE}/{ig_id}/media",
        params={
            "fields": "id,caption,timestamp,media_type",
            "limit": str(media_limit),
            "access_token": token,
        },
        timeout=30,
    )
    resp.raise_for_status()
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
# main
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Publish an Instagram Story.")
    parser.add_argument("--dry-run", action="store_true", help="only show what would be published")
    parser.add_argument("--url", help="override the image URL to publish")
    parser.add_argument("--image", help="publish a specific file from stories/playlist.json (uses its caption)")
    parser.add_argument("--feed", action="store_true", help="publish as a feed post (grid) instead of a Story")
    parser.add_argument("--caption", help="caption text (feed posts)")
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
    print(f"[OK] {kind} published! (post id: {post_id})")


if __name__ == "__main__":
    main()