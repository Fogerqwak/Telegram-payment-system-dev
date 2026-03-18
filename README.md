# Telegram Payment System (Private Channel Access Bot)

Centralized Telegram bot for selling access to **private Telegram channels/groups** using:

- **Crypto / stablecoins** via Coinbase Commerce (pluggable)
- **Stripe** (Checkout)
- **PayPal** (v2 Orders API)

This repo is a clean base inspired by patterns in [`env0id/Bet-bot`](https://github.com/env0id/Bet-bot.git) but focused on **payments + access control** rather than betting.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
mkdir -p data

python -m app.main
```

## Telegram setup (required)

1. Create a bot with `@BotFather` and set `TELEGRAM_BOT_TOKEN`.
2. Add the bot as an **admin** in the protected channel/group (`PROTECTED_CHAT_ID`) with permission to:
   - Invite users via link (Manage Chat / Invite Users)
   - (Optional) Ban/unban members if you want revocation features
3. Put your Telegram numeric user id into `ADMIN_USER_IDS` so you can administer plans and grants.

## How access works

- User runs `/buy` → bot creates a payment with the chosen provider → returns a checkout URL.
- Bot periodically checks payment status.
- When paid, bot creates a **one-time invite link** and sends it to the user.
- User joins the protected chat with that link.

## Payments

This base supports **MOCK mode** so you can run without keys:

- Set `MOCK_PAYMENTS=true` in `.env` (default in `.env.example`)
- Bot will generate “fake paid” checkouts after a short delay (for end-to-end testing).

When you’re ready, disable mock and enable providers:

- Stripe: set `STRIPE_ENABLED=true` and `STRIPE_SECRET_KEY`
- PayPal: set `PAYPAL_ENABLED=true` and credentials
- Coinbase: set `COINBASE_ENABLED=true` and `COINBASE_API_KEY`

## Commands

- `/start` – intro
- `/buy` – buy default plan
- `/status <payment_id>` – check a payment

Admin:

- `/setplan <plan_id> <name> <price_cents> <duration_days>`
- `/grant <user_id> <days>`
- `/revoke <user_id>`

## Notes / next steps (recommended)

- Add webhooks (Stripe + Coinbase + PayPal) for instant confirmations
- Add multi-plan UI with inline buttons
- Add subscription renewals and grace periods
- Add AML / fraud rules and manual review queue

