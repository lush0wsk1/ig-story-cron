# Instagram Story Cron

Publishes one of your preset images as an Instagram Story **every 3 hours**,
using the official Instagram Graph API (Stories publishing) on your **own
Instagram Business account**. Free, no subscriptions, no app-review red tape
(it runs in Development Mode for your own account).

## ✅ Setup checklist (where you are)

| # | Step | Done |
|---|------|------|
| 1 | Facebook Page created (in Business Suite) | ☑️ |
| 2 | Instagram account type = **Business** (not Creator) | ☑️ |
| 3 | Instagram linked to the Facebook Page | ☑️ |
| 4 | Meta developer app created ("Brand Story Publisher") | ☑️ |
| 5 | Product **Instagram** added + IG account accepted as tester | ☑️ |
| 6 | **Get the access token** (Graph API Explorer) | ⬜ ← NOW |
| 7 | Fill `.env` + local test story | ⬜ |
| 8 | GitHub Actions cron | ⬜ |

## Getting the token (step 6)

1. Open **developers.facebook.com/tools/explorer** (logged in with your Facebook).
2. Top dropdown → select **"Brand Story Publisher"**.
3. **Get Token → User Access Token** → **Continue**.
4. Copy the string that starts with `EAAG…`.

> You do **not** need the "Instagram app secret" (lopcprospa - IG) for this
> pipeline. Ignore it.

## Local test (step 7)

```bash
cd instagram-story-cron
cp .env.example .env      # fill APP_ID, APP_SECRET, IG_USER_TOKEN, PUBLIC_BASE_URL
python -m venv .venv && source .venv/bin/activate
pip install requests python-dotenv

python publish_story.py --dry-run   # see what it will publish (no API post)
python publish_story.py --now       # publish the current slot right now
```

The first run converts your token into a long-lived (60-day) token (stored in
`.env`). Each run refreshes it, so the cron stays alive.

## GitHub Actions cron (step 8)

1. Push this project to a **public** GitHub repo (images included) → set
   `PUBLIC_BASE_URL` to the jsDelivr URL (see `stories/README.md`).
2. Repo → Settings → Secrets and variables → Actions → add:
   - `APP_ID`, `APP_SECRET`, `IG_USER_TOKEN`, `IG_BUSINESS_ACCOUNT_ID`
     (optional), `PUBLIC_BASE_URL`
3. The workflow `publish-stories.yml` already runs `0 */3 * * *`. Trigger it
   once manually (Actions → Run workflow) to test.

## Maintenance

- **Token:** the workflow refreshes the token on every run; GitHub Actions
  stores the ORIGINAL token in Secrets, which expires after ~60 days. Every ~2
  months, refresh it locally (`python publish_story.py --refresh-only`) and
  update the secret. (On a personal VPS/cron the `.env` updates itself — no
  chore.)
- **Warm-up:** for a brand-new account, post manually for 1–2 weeks before
  enabling the cron, and consider starting at 2–3/day.

## Notes / limits

- 25 publishes/day max via API → 8/day at every-3-hours is fine.
- Stories API requires a **Business** account (Creator won't work).
- 2FA should be an authenticator app, not SMS.