# Changelog — glitchexecutor (private)

All notable changes to the Glitch Executor platform are logged here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

**Private repo — full operational detail is OK here** (account IDs, server
paths, ops runbook specifics). Public-facing repos (ouroboros, ml-data)
use a redacted variant of these entries.

---

## [Unreleased]

### Changed — 2026-04-14 · GitHub migration to `glitch-exec-labs`

- All 13 repos transferred from the old `glitch-executor` user account to
  the `glitch-exec-labs` user account (GitHub Pro).
- Git remote on `/opt/glitchexecutor/.git/config` repointed from
  `git@github.com:glitch-executor/glitchexecutor.git` → HTTPS with PAT:
  `https://<token>@github.com/glitch-exec-labs/glitchexecutor.git`.
  (SSH from this server isn't authorized on the new GitHub account;
  HTTPS with PAT is the working path.)
- GitHub Actions secrets `SERVER_HOST` (136.115.184.123), `SERVER_USER`
  (`support`), and `SERVER_SSH_KEY` re-set on the new repo.
- The server's own SSH public key was added to `~support/.ssh/authorized_keys`
  so the `appleboy/ssh-action` SSH-back-to-self pattern works. Without
  that the workflow failed with `ssh: handshake failed: unable to
  authenticate, attempted methods [none publickey]`.

### Changed — 2026-04-14 · Production cTrader creds swapped to production token

- `/opt/glitchexecutor/.env` (and `ml_collector/.env`):
  - `CTRADER_CLIENT_ID` — app `24429` on openapi.ctrader.com
  - `CTRADER_CLIENT_SECRET` — stored in `.env` only
  - `CTRADER_ACCESS_TOKEN` swapped from sandbox token to production token
    via OAuth code exchange at
    `https://connect.spotware.com/apps/auth?client_id=…&redirect_uri=https://glitchexecutor.com/ctrader/callback&scope=trading`
    (30-day expiry)
  - `CTRADER_REFRESH_TOKEN` saved alongside (enables silent renewal)
  - Actual values live only in `/opt/glitchexecutor/.env` and
    `/opt/glitch-ouroboros/ctrader/ml_collector/.env` — never in git.
- Verified token exposes all 16 accounts (9 live + 7 demos).
- `CTRADER_ACCOUNT_ID` changed from Deriv live `46868136` → Pepperstone
  spare demo `46966102` so the executor is processing real orders on a
  demo. Flip to a funded account when ready.
- `EXECUTOR_MOCK_MODE=false` — ensemble → executor trades now go through
  real cTrader API calls (to the demo account).

### Fixed — 2026-04-14 · `executor/ctrader_client.py` ProtoOATraderReq payload type

- `PT_TRADER_REQ / PT_TRADER_RES` were declared `2104 / 2105` but the
  correct values are `2121 / 2122`. With the wrong constants the request
  went out under the wrong payloadType and the reply parsed into an
  empty `ProtoOATraderRes`, so `get_balance()` silently returned zeros.
- Silent while `EXECUTOR_MOCK_MODE=true` (mock path never calls
  `get_balance`). Surfaced the moment we flipped LIVE: every closed
  row in `ml_trades` had `account_balance = 0` and `account_equity = 0`.
- Fix applied to both the main platform's `executor/ctrader_client.py`
  (used by the Docker executor container) and the vendored copy inside
  `ctrader/executor/` in the ouroboros repo (used by `ml_collector`).
- Backfill is not trivial (would need historical snapshots of balance
  at each closure timestamp). Accept zeros for pre-fix rows; going
  forward all rows populate correctly.

### Fixed — 2026-04-14 · `executor/ctrader_client.py` import + protobuf bugs

1. `ProtoOAOrderType` and `ProtoOATradeSide` were imported from
   `OpenApiMessages_pb2` where they do not exist; they live in
   `OpenApiModelMessages_pb2`. This caused `PROTO_AVAILABLE = False` and
   the executor ran in MOCK mode silently even when `EXECUTOR_MOCK_MODE=false`.
2. `_reconcile()` read `pos.unrealizedPnl`, a field that does not exist
   on `ProtoOAPosition` in the current protobuf spec. Every
   `get_open_positions` call failed with
   `Protocol message ProtoOAPosition has no non-repeated field
   "unrealizedPnl"`. Drop the field, return `profit=0`, and note that
   authoritative P&L must come from `ProtoOADealListReq`.
3. Restored `executor/prop_firm_guard.py` — module was imported by
   `worker.py:24` but missing from the initial commit; source recovered
   from `/home/support/TRANSFER_PACKAGE/bot_code/shared_modules/`.
4. Rebuilt the `glitch-executor` Docker container with `--no-cache` so
   `ctrader-open-api` is actually present in the image.

### Changed — 2026-04-14 · CI/CD workflows hardened

- `deploy-platform.yml` — now also runs
  `sudo systemctl restart glitch-ml-collector.service` after the Docker
  compose step. Requires the sudoers rule added today (see Ops below).
- `deploy-website.yml` — added `workflow_dispatch` trigger and `set -e`.
  Deploys `website/` → `/var/www/glitchexecutor/landing/` via rsync.
- `deploy-dashboard.yml` — added `workflow_dispatch`, `set -e`, and
  dropped the redundant runner-side `npm ci && npm run build`. Server
  now builds exactly once using Node 22. Deploys
  `admin_frontend/dist/` → `/var/www/glitchexecutor/admin/`.

### Changed — 2026-04-14 · ml_collector moved to its own repo

- `/opt/glitchexecutor/ml_collector/` archived as `ml_collector.OLD-20260414/`
  (gitignored).
- The six-bot stack now lives in
  `glitch-exec-labs/glitch-ouroboros-snake-strategy` under `ctrader/`
  and runs from `/opt/glitch-ouroboros/ctrader/`. See that repo's
  `CHANGELOG.md` for the bot-side details (adaptive sizer, JPY fix,
  classifier fix, per-TF `notional_pct` defaults).

### Ops — sudoers file `/etc/sudoers.d/glitch-deploy`

Deploy-user (`support`) has narrow-scope passwordless sudo for:

```
support ALL=(ALL)      NOPASSWD: /bin/systemctl restart glitch-ml-collector.service
support ALL=(glitchml) NOPASSWD: /usr/bin/git -C /opt/glitch-ouroboros pull origin main
support ALL=(glitchml) NOPASSWD: /usr/bin/git -C /opt/glitch-ouroboros pull
support ALL=(ALL)      NOPASSWD: /usr/bin/rsync -av --delete /opt/glitchexecutor/website/ /var/www/glitchexecutor/landing/
support ALL=(ALL)      NOPASSWD: /usr/bin/rsync -av --delete /opt/glitchexecutor/admin_frontend/dist/ /var/www/glitchexecutor/admin/
support ALL=(ALL)      NOPASSWD: /bin/systemctl reload nginx
```

### Ops — disk cleanup

- Moved 2.4 GB of migration artifacts to `/home/support/_REVIEW_TO_DELETE/`:
  `TRANSFER_PACKAGE*`, `workspace/deriv-xau-bot`, `workspace/xau-review`,
  `workspace/nba-cloudbet-bot`, `engine_v2.py`, `inspect_models.py`.
- `/home/ubuntu/.openclaw/workspace/` (2.5 GB) left in place — two active
  systemd services depend on it (`discussion-board.service` and
  `glitchexecutor-subdomains.service`).

---

## [0.1.0] — 2026-04-11

Initial commit of the Glitch Executor trading platform:

- `ensemble/` — 7-model AI ensemble engine
- `executor/` — trade execution service (cTrader + ccxt)
- `telegram_bot/` — main Telegram bot service
- `admin_api/` — FastAPI admin dashboard backend
- `admin_frontend/` — React admin dashboard (served at
  dashboard.glitchexecutor.com)
- `payment/` — Stripe payment processing
- `website/` — public landing page (served at glitchexecutor.com)
- `docker-compose.yml` — 9-service Docker stack (redis, postgres,
  ensemble, telegram_bot, executor, payment, admin_api, dashboard nginx,
  docker-proxy)
- `.github/workflows/` — deploy-platform / deploy-website / deploy-dashboard
