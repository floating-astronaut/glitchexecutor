# Changelog — `glitchexecutor`

Auto-regenerated from `git log` by `/home/support/bin/changelog-regen`,
called before every push by `/home/support/bin/git-sync-all` (cron `*/15 * * * *`).

**Purpose:** traceability. If a push broke something, scan dates + short SHAs
here; then `git show <sha>` to see the diff, `git revert <sha>` to undo.

**Format:** UTC dates, newest first. Each entry: `time — subject (sha) — N files`.
Body text (if present) shown as indented sub-bullets.

---

## 2026-05-17

- **05:32 UTC** — auto-sync: 2026-05-17 05:32 UTC (`b78f837`) — 1 file
        M	admin_api/routers/ctrader_oauth.py

## 2026-05-16

- **23:07 UTC** — admin_api: align with trade-app → trade.glitchexecutor.com rename (`5e095a1`) — 2 files
    The trade SPA hostname moved from trade-app.* to trade.* when it
    landed on CF Pages. Two real fixes:
      - CORSMiddleware allow_origins now includes the new hostname
        (kept the old one too as a short-term transition courtesy).
      - cTrader OAuth REDIRECT_URI default now points at trade.* so the
        hardcoded fallback matches what's registered in the Spotware dev
        portal. Production also pins CTRADER_PUBLIC_REDIRECT_URI in env.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
- **22:17 UTC** — auto-sync: 2026-05-16 22:17 UTC (`4c841ea`) — 3 files
        M	admin_api/main.py
        A	admin_api/routers/trade_admin.py
- **03:04 UTC** — ctrader oauth: pass access token as ?oauth_token= query param (`45a0e36`) — 2 files
    Spotware's /connect/tradingaccounts rejects 'Authorization: Bearer …'
    with INVALID_REQUEST 'Required oauth_token parameter is not present'.
    Switch to the documented query-param form.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## 2026-05-15

- **08:03 UTC** — admin_api: cTrader Open API multi-tenant OAuth router + DB migration (`0e3c9f6`) — 4 files
    Lets every signed-in SSO user link one or more of their personal cTrader
    trader accounts via the standard OAuth 2.0 authorization-code flow.
    Sister of the existing /api/customers proxy: routers stay thin, secrets
    live in env, tokens get encrypted at rest before they touch Postgres.
    routers/ctrader_oauth.py
      GET    /api/ctrader/oauth/start          mints CSRF state JWT bound
                                               to the SSO email; returns
                                               the cTrader authorize URL
                                               the SPA should send the
                                               browser to
- **07:04 UTC** — auto-sync: 2026-05-15 05:48 UTC (`92c5bac`) — 3 files
        M	admin_api/auth.py
        M	admin_api/main.py
- **05:33 UTC** — auto-sync: 2026-05-12 10:10 UTC (`6ed4860`) — 2 files
        M	payment/server.py

## 2026-05-12

- **09:43 UTC** — admin_api: customers proxy (JWT-auth → X-Fulfill-Secret → payment service) (`903bf04`) — 2 files
    New routers/customers.py forwards 7 endpoints to the payment service:
      GET  /api/customers/buyers              → GET  /api/grow/buyers
      GET  /api/customers/buyer/{payment_id}  → GET  /api/grow/buyer/{id}/detail
      GET  /api/customers/leads               → GET  /api/grow/leads
      POST /api/customers/refund              → POST /api/grow/refund-buyer
      POST /api/customers/resend-welcome      → POST /api/grow/resend-welcome
      POST /api/customers/reinvite-codeberg   → POST /api/grow/reinvite-codeberg
      POST /api/customers/note                → POST /api/grow/buyer-note
    All endpoints require JWT via the existing get_current_user. The
    X-Fulfill-Secret header is added server-side from env so the SPA never
- **07:18 UTC** — admin_api: add /api/grow/agents/summary for command center (`b17470d`) — 1 file
    One row per Grow agent (sales/ads/social/ugc/seo/voice) with status,
    deployments, pending_approvals, outputs_7d. Sales pulls real counts
    from sales_agent.email_drafts (pending) and email_sends (last 7d);
    other agents are coming_soon stubs until they have data sources.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
- **05:46 UTC** — admin_api: surface open positions + floating PnL on /api/trade/account/live (`bd80cbc`) — 1 file
    Pass through the new fields the ml_collector live_balance loop now writes:
    total_open_positions, total_open_lots, total_floating_pnl, and per-account
    open_positions / open_lots / floating_pnl.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
- **05:32 UTC** — admin_api: add /api/trade/account/live for broker balance snapshot (`6de7a34`) — 1 file
    Trivial DB read of ml_collector_state['live_balance'], which is now
    populated every 30s by the ml_collector live_balance_loop. Returns
    total + per-account balance/equity and a stale_seconds freshness gauge
    so the dashboard can warn if the broker poll has stopped.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
- **05:04 UTC** — admin_api: add /api/trade/series for sparkline KPIs (`195af1d`) — 1 file
    Daily-bucketed time series (pnl, equity, signals, trades) over a configurable
    window. Backs the new sparklines on the Trade Overview KPI cards.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## 2026-05-06

- **01:53 UTC** — feat(grow): Postgres buyer ledger + record/list/refund endpoints (`32814ba`) — 2 files
    Adds glitch_grow_buyers table to the existing postgres container and
    three Flask routes that the Cloudflare Pages fulfillment Function on
    grow.glitchexecutor.com calls into via mcp.glitchexecutor.com (the
    gray-clouded direct-to-host subdomain already used for the Stripe
    webhook proxy).
    Schema (idempotent CREATE TABLE IF NOT EXISTS):
      glitch_grow_buyers
        id BIGSERIAL PK
        payment_id TEXT UNIQUE          (idempotency key)
        provider TEXT CHECK in ('stripe','razorpay')
- **01:37 UTC** — stripe webhook: fork on metadata.sku=BSK-* for Glitch Grow fulfillment (`eb5cdc6`) — 1 file
    Glitch Grow Payment Links (BSK-001..006 + BSK-ALL) now flow into the
    checkout.session.completed handler with their existing metadata.sku
    tag from setup-stripe-products.mjs. When seen, fork to the central
    fulfillment endpoint at grow.glitchexecutor.com/api/fulfill/grant-access
    and skip the dashboard subscription branch below.
    Auth: shared secret via GROW_FULFILL_SECRET env var matched against
    the Cloudflare Pages env FULFILL_SECRET. Network error or missing
    secret logs a warning and is otherwise non-blocking — Stripe retries
    are acceptable, the Pages Function is idempotent on session_id.
    Adds GitHub username from session.custom_fields[key=github_username]

## 2026-05-05

- **09:35 UTC** — fix(nginx): route payment-owned /api paths to payment service, not admin_api (`e64ea8f`) — 1 file
    Stripe has been retrying our webhook 152 times since May 2 09:23 UTC
    because the apex routed every /api/* to admin_api:5003, which has no
    /api/stripe/webhook handler — hence 405 Method Not Allowed.
    The payment Flask service (:5002) actually owns the Stripe + Telegram
    + lead-capture routes. Add explicit location blocks so they hit the
    right upstream, with the generic /api/ rule still catching everything
    else for admin_api.
    Webhook block disables proxy_request_buffering and proxy_buffering so
    the raw body reaches Flask intact for HMAC signature verification —
    nginx must not modify the bytes Stripe signed.

## 2026-04-30

- **23:52 UTC** — feat(grow): /api/grow/budz/* — read-only Glitch Budz (sales_agent) (`c34f586`) — 4 files
    First Grow-vertical backend. Reads from the live host postgres
    glitch_sales_agent DB (sales_agent schema) — 655 leads, 197 drafts,
    45 sends as of writing.
    DB plumbing:
    - New get_sa_pg() helper in db.py against SA_DATABASE_URL.
    - New glitch_sa_ro postgres role (NOINHERIT, SELECT only on
      sales_agent schema). Same unix-socket transport as the ml DB
      (no host-postgres restart, just pg_hba.conf reload).
    - docker-compose admin_api gets SA_DATABASE_URL env wired through
      ${SA_RO_PASSWORD}, search_path pinned to sales_agent,public.
- **23:44 UTC** — feat: date_from/date_to + pagination on remaining tables (`ff4c3ff`) — 3 files
    - /api/settings/audit: + date_from, date_to (filters audit_log.created_at)
    - /api/billing/email-signups: + date_from, date_to + fix pre-existing
      bug — SQL referenced "signed_up_at" but the column is actually
      "created_at". Endpoint always 500'd; the dashboard silently rendered
      the blank "No email signups yet" empty-state. Aliased the new column
      AS signed_up_at to avoid touching the frontend mapping.
    - /api/admin/customers: + date_from, date_to (filters customers.created_at)
    Same _apply_date_range pattern: ">= timestamptz" lower bound and
    "< (date + 1 day)" exclusive upper bound, so a single-day pick is
    inclusive on both ends.
- **18:57 UTC** — feat: server-side date_from/date_to + pagination on all heavy tables (`e723899`) — 2 files
    Every table-bearing endpoint now accepts date_from / date_to query
    params (YYYY-MM-DD, inclusive on both ends) and returns a uniform
    {total, page, limit, rows} response shape.
    trade.py:
    - New _apply_date_range helper for consistent inclusive date filtering.
    - /signals: + date_from, date_to (filters created_at).
    - /trades: + date_from, date_to (filters opened_at).
    - /oracle/decisions: + date_from, date_to + pagination (was returning
      bare list, now Page<T>).
    - /oracle/blocks: + date_from, date_to + pagination (was bare list).
- **06:28 UTC** — fix(admin_api): control_centre containers endpoint returns 500 (`887111f`) — 1 file
    Two issues — same root causes as the prior infra.py fix.
    1. c.image.tags[0] triggered a /images/{id}/json call to docker-socket-
       proxy, which is denied (403) → entire /api/cc/containers errored 500.
       Switched to attrs.Config.Image (already loaded with the container
       info) — no extra API call needed.
    2. TARGET_CONTAINERS still listed glitch-ensemble, glitch-telegram-bot,
       glitch-executor (retired). Replaced with the live set: postgres,
       redis, payment, admin-api, dashboard, docker-proxy.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
- **05:51 UTC** — chore(admin_api): infra + settings cleanup post legacy retirement (`0e5c27f`) — 2 files
    infra.py:
    - TARGET_CONTAINERS no longer lists the dead containers
      (ensemble, telegram-bot, executor) — they were always rendering as
      "not_found" since the prior retirement commit. Added the live ones
      it was missing: glitch-dashboard, glitch-docker-proxy.
    - Added a derived "glitch-ml-collector" host pseudo-service: status
      inferred from ml_signals freshness (healthy <120s, stale <600s,
      stopped beyond). Same logic the dashboard router uses for the
      Trade Engine KPI.
    - Switched image lookup to read attrs.Config.Image instead of
- **05:38 UTC** — feat(admin_api): admin home reads from Ouroboros, drops dead ensemble checks (`c117d79`) — 1 file
    dashboard.py rewrite:
    - KPI: replaced ensemble_status (was checking dead glitch-ensemble:8100)
      with trade_engine status derived from ml_signals freshness
      (healthy <120s, stale <600s, offline beyond).
    - KPI: added trades_open, trades_today, signals_today, account_equity
      pulled from glitch_ml.
    - Removed auto_execute_trades_today / auto_execute_users / strong_signal_*
      fields — they read from the deprecated trades + user_preferences tables
      tied to the retired telegram bot.
    - /alerts: replaced "ensemble unreachable" check with trade_engine
- **05:07 UTC** — feat(admin_api): trade vertical reads from Ouroboros (glitch_ml) (`6eaec9f`) — 9 files
    Backend rebuild for the Trade vertical:
    - New router /api/trade/* with read-only access to the host postgres
      glitch_ml DB (Ouroboros cTrader demo data) via mounted unix socket.
    - Endpoints: bots, signals, trades, stats, symbols, oracle/{decisions,
      weights,blocks,risk}, news, state, bars/{symbol}/{tf}.
    - Connection: dedicated psycopg2 pool to glitch_ml as a new read-only
      postgres role glitchml_ro (NOINHERIT, SELECT only).
    - docker-compose: admin_api now bind-mounts /var/run/postgresql:ro and
      receives ML_DATABASE_URL env (postgresql://glitchml_ro:.../glitch_ml
      via unix socket — no postgres restart, no TCP exposure required).
- **04:42 UTC** — chore: drop ensemble/executor/telegram_bot service blocks from compose (`6d4cbd0`) — 1 file
    Follow-up to 9fb30d2 — the previous commit deleted the source folders
    but missed the docker-compose.yml edit. Without this, a redeploy would
    fail (build paths gone) or recreate the dead services if the folders
    were restored.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
- **04:42 UTC** — chore: retire legacy ensemble/executor/telegram_bot stack (`925022a`) — 73 files
    Remove three dead services that were churning on broken dependencies
    with zero users (0 telegram_users, 0 signal_subscriptions, 0 alerts):
    - ensemble: cTrader symbol cache failures, no successful signals
    - executor: Binance testnet HTTP 451 (geo-blocked)
    - telegram_bot (@GlitchExecutor_bot): scheduling jobs against the
      broken ensemble for an empty subscriber list
    All trading is now handled by the live Ouroboros stack
    (glitch-ml-collector.service, cTrader demo, separate glitch_ml DB).
    Containers stopped and removed on the running host; this commit makes
    the change permanent so a redeploy doesn't resurrect them.

## 2026-04-19

- **08:20 UTC** — chore: extract admin_frontend into glitch-admin-dashboard repo (`b6670e6`) — 40 files
    Dashboard UI moves out to its own standalone repo as part of the
    platform rebuild. Drops the admin_frontend tree, the compose nginx
    service that served its dist bundle, and the legacy deploy workflow.
    The new repo owns its own CI/hosting end-to-end.
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## 2026-04-17

- **02:26 UTC** — chore: add gitleaks pre-commit hook (`41b3db5`) — 1 file
    Blocks commits containing API keys, tokens, or other secrets.
    Install locally: pre-commit install
    Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

## 2026-04-14

- **17:30 UTC** — docs: record retirement of ml-data git sync (`c530915`) — 1 file
- **17:20 UTC** — docs: log PT_TRADER payload-type fix in CHANGELOG (`6ea1e61`) — 1 file
- **17:19 UTC** — fix(executor): correct ProtoOATraderReq/Res payload type (`cf9c90c`) — 1 file
    Same fix as ouroboros repo. 2104/2105 are a different message type; the
    correct payload types for ProtoOATraderReq/Res are 2121/2122. With the
    wrong constants the wire request was parsed as an unrelated message on
    the Spotware side, which returned an empty ProtoOATraderRes (balance=0).
    This was silent while EXECUTOR_MOCK_MODE=true (get_balance only invoked
    at trade time, and MOCK mode skipped it). Now that we're LIVE, the
    admin ensemble path needs real balance for PropFirmGuard / position
    sizing — fix lands just in time.
    Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
- **13:37 UTC** — docs+fix: add CHANGELOG.md and commit pending code fixes (`2e03bcb`) — 4 files
    CHANGELOG.md records all 2026-04-14 platform changes: GitHub migration
    to glitch-exec-labs, production cTrader token, executor protobuf fixes,
    CI/CD hardening, ml_collector relocation to the ouroboros repo, and the
    sudoers/disk ops performed on the server. This is a private repo so the
    CHANGELOG keeps full operational detail (account IDs, server paths,
    credential references). Public-facing repos use a redacted variant.
    Pending code fixes being captured in this commit:
    - executor/ctrader_client.py: fix ProtoOAOrderType/ProtoOATradeSide
      imports (they live in OpenApiModelMessages_pb2, not OpenApiMessages_pb2)
    - executor/ctrader_client.py: drop pos.unrealizedPnl read (field does
- **07:22 UTC** — ci: add workflow_dispatch + set -e + drop redundant runner-side build (`610c291`) — 2 files
    - Both website and dashboard workflows gain workflow_dispatch so they can
      be triggered manually from the Actions tab when we need to re-sync
      without a code change.
    - Dashboard workflow was building on the GitHub runner AND the server
      (the runner output was discarded). Drop the runner-side build; do it
      once on the server.
    - set -e so any step failure surfaces as a red run instead of silently
      continuing.
    Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
- **04:00 UTC** — ci: restart ml-collector after deploy and point to glitch-exec-labs (`8491e8d`) — 1 file
    Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

## 2026-04-11

- **20:19 UTC** — Add or polish private repo README (`8755acd`) — 1 file

## 2026-04-10

- **22:17 UTC** — Initial commit — Glitch Executor platform, dashboard, and website (`11453be`) — 171 files
    Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
