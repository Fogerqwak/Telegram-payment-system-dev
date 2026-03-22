# Telegram Payment System (Private Channel Access Bot)

Centralized Telegram bot for selling access to **private Telegram channels/groups** using:

- **Crypto Pay** ([`pay.crypt.bot`](https://pay.crypt.bot)) — USDT invoices via [@CryptoBot](https://t.me/CryptoBot)
- **Stripe** (Checkout)
- **PayPal** (v2 Orders API)

This repo is a clean base inspired by patterns in [`env0id/Bet-bot`](https://github.com/env0id/Bet-bot.git) but focused on **payments + access control** rather than betting.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env
mkdir -p data

python -m app.main
```

The process runs **two services** in one event loop:

- **Telegram** long polling (updates for messages and callback queries)
- **FastAPI + Uvicorn** on `WEBHOOK_HOST` / `WEBHOOK_PORT` (default `0.0.0.0:8000`) for payment webhooks

Point your provider webhook URLs at the public HTTPS address that forwards to that port (for example Stripe: `/webhooks/stripe`, Crypto Pay: `/webhooks/cryptobot`, PayPal: `/webhooks/paypal`). See comments in `app/webhooks/app.py` for which headers and secrets each route expects.

## Telegram setup (required)

1. Create a bot with `@BotFather` and set `TELEGRAM_BOT_TOKEN`.
2. Add the bot as an **admin** in the protected channel/group (`PROTECTED_CHAT_ID`) with permission to:
   - Invite users via link (Manage Chat / Invite Users)
   - Ban/unban members (used when subscriptions expire and for admin `/revoke`)
3. Put your Telegram numeric user id into `ADMIN_USER_IDS` so you can administer plans and grants.

## How access works

- User runs `/buy` → inline keyboard: **plan** → **provider** → **Pay now** (URL) and **Check payment**.
- Plans are stored in SQLite (`plans` table), seeded on first run from `AVAILABLE_PLAN_IDS` and `PLAN_<id>_*` env vars (see `.env.example`).
- The bot **polls** pending payments on a short interval and can also **confirm instantly** via HTTP webhooks (Stripe, Crypto Pay, PayPal).
- When a payment is **paid**, the bot calls `grant_access`: creates a **short-lived one-time invite link** (10 minutes), sends it in DM, and extends the user’s subscription row.
- **Expired subscriptions**: an hourly job deactivates them, bans then unbans the user in the protected chat (so they can rejoin only with a new invite), and notifies them to use `/buy` again.

## Payments

**MOCK mode** (no external APIs):

- Set `MOCK_PAYMENTS=true` in `.env` (default in `.env.example`).
- The bot uses a fake checkout URL and marks the payment paid after a short delay for end-to-end testing.

**Real providers** — disable mock and enable only what you need (see `.env.example`):

| Provider   | Enable flag            | Notes |
|-----------|------------------------|--------|
| Stripe    | `STRIPE_ENABLED=true`  | Needs `STRIPE_SECRET_KEY`, success/cancel URLs, and `STRIPE_WEBHOOK_SECRET` for `/webhooks/stripe` |
| PayPal    | `PAYPAL_ENABLED=true`  | Needs client id/secret, return/cancel URLs, and `PAYPAL_WEBHOOK_ID` for `/webhooks/paypal` |
| Crypto Pay | `CRYPTOBOT_ENABLED=true` | Needs `CRYPTOBOT_TOKEN`; configure the webhook URL in [@CryptoBot](https://t.me/CryptoBot) → app → Webhooks |

## Commands

- `/start` — intro and plan summary from the database
- `/buy` — choose plan and provider (inline keyboards), then pay or check status
- `/status <payment_id>` — refresh status from the provider (and grant access if already paid)

**Admin**

- `/setplan <plan_id> <name> <price_cents> <duration_days>` — upsert a plan in the database
- `/grant <user_id> <days>` — extend access for a user (uses `DEFAULT_PLAN_ID` for the plan id)
- `/revoke <user_id>` — remove subscription row for that user

## Configuration

All settings are loaded with **pydantic-settings** from `.env`. Copy `.env.example` and fill in values; nothing secret should be hardcoded in code.

## Optional next steps

- Harden operational security (rate limits, idempotency keys, monitoring).
- Add renewal reminders before `active_until`.
- Add manual review or fraud rules if you scale volume.
