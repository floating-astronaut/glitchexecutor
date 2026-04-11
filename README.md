# GlitchExecutor

Private multi-service trading intelligence platform for the Glitch ecosystem.

GlitchExecutor is the integrated application layer that sits above the strategy repos: user-facing Telegram flows, admin tooling, ensemble analysis, execution services, billing, and deployment infrastructure. This repo is private because it contains the operational product surface rather than just isolated strategy code.

## Repo Role

This repository combines:

- the AI ensemble service
- the execution worker layer
- the Telegram bot experience
- the admin API and frontend
- payment and subscription infrastructure
- Docker-based deployment for the platform stack

## Top-Level Structure

- `ensemble/` for market analysis, orchestration, and price-feed logic
- `executor/` for execution workers and position handling
- `telegram_bot/` for the user-facing bot, alerts, and orchestration
- `admin_api/` for internal platform APIs
- `admin_frontend/` for dashboard UI
- `payment/` for billing and payment-service flows
- `website/` for marketing/site assets
- `nginx/` and `docker-compose.yml` for deployment plumbing

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the detailed internal system map, service boundaries, data flow, and database notes.

## Privacy

This repository must remain private.

Do not commit production secrets, live customer data, database dumps, payment credentials, or unredacted operational configuration. Keep this repo limited to platform code and sanitized internal documentation.

## Relationship To Other Repos

- strategy repos define reusable trading logic and product identities
- private data/model repos preserve the ML and research estate
- `glitchexecutor` is the integrated platform surface that ties those pieces into a working product
