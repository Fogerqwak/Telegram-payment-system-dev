# Telegram Payment System (Private Channel Access Bot)

Centralized Telegram bot for selling access to **private Telegram channels/groups**. User-facing copy is **Russian**; payments can use **Telegram Stars (XTR)**, **Crypto Pay** ([`pay.crypt.bot`](https://pay.crypt.bot), USDT via [@CryptoBot](https://t.me/CryptoBot)), **Stripe** (Checkout), or **PayPal** (v2 Orders API).

This repo is a clean base inspired by patterns in [`env0id/Bet-bot`](https://github.com/env0id/Bet-bot.git), focused on **payments + access control**.

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

- **Telegram** long polling (messages, **callback queries**, **pre-checkout queries** for Stars, and **successful payments**)
- **FastAPI + Uvicorn** on `WEBHOOK_HOST` / `WEBHOOK_PORT` (default `0.0.0.0:8000`) for payment webhooks

Point your provider webhook URLs at the public HTTPS address that forwards to that port:

| Endpoint | Provider | Notes |
|----------|----------|--------|
| `/webhooks/stripe` | Stripe | Header `Stripe-Signature`, secret `STRIPE_WEBHOOK_SECRET` |
| `/webhooks/cryptobot` | Crypto Pay | Header `crypto-pay-api-signature`, HMAC-SHA256 with `CRYPTOBOT_TOKEN` |
| `/webhooks/paypal` | PayPal | Verified via PayPal API using `PAYPAL_WEBHOOK_ID` |

Details are in `app/webhooks/app.py`.

## Telegram setup (required)

1. Create a bot with `@BotFather` and set `TELEGRAM_BOT_TOKEN`.
2. Add the bot as an **admin** in the protected channel/group (`PROTECTED_CHAT_ID`) with permission to:
   - Invite users via link (create invite links)
   - Ban/unban members (used when subscriptions expire and for admin `/revoke`)
3. Put your Telegram numeric user id into `ADMIN_USER_IDS` so you can administer plans and grants.
4. Optional: set `SUPPORT_USER_IDS` (or leave empty to reuse admins) for `/support` forwarding.

## How access works

- After `/start`, the bot shows a **reply keyboard** under the message input (persistent menu): **Купить**, **Статус**, **Поддержка** — same actions as `/buy`, `/status` (subscription), and `/support`. Inline buttons under messages are still used for plan and payment method selection.
- User runs `/buy` (or taps **Купить**) → **three steps** (inline keyboards): **choose plan** → **choose payment method** → **pay** (Stars opens an invoice in the chat; other providers get a **Pay** URL plus **Check payment**).
- **Telegram Stars** is listed first when `STARS_ENABLED=true`. No external checkout URL: the bot calls `send_invoice` with `currency=XTR` and `provider_token=""`.
- Plans live in SQLite (`plans` table), seeded on first run from `AVAILABLE_PLAN_IDS` and `PLAN_<id>_*` env vars (including `PLAN_<id>_STARS_PRICE` for Stars amounts). Each plan has `price_cents`, `duration_days`, and `stars_price`. The stock example is one **3‑month** tier at **39,99 €** (`quarterly` in `.env.example`; `DISPLAY_CURRENCY=EUR`).
- **Stripe / Crypto Pay / PayPal**: pending payments are **polled** on a short interval and can be **confirmed** via HTTP webhooks. **Stars** are **not** polled; confirmation is **push-only** (`PreCheckoutQuery` + `SuccessfulPayment`).
- When payment is confirmed, the bot calls `grant_access`: extends the subscription (`add_days` / stacking), creates a **one-time invite link** (15 minutes, `member_limit=1`), and sends a Russian DM with the link and subscription end date.
- **Expired subscriptions**: an **hourly** job (scheduler, `UTC`) deactivates expired rows, bans then unbans the user in the protected chat, and sends a Russian reminder to run `/buy`.

## Payments

**MOCK mode** (no external APIs):

- Set `MOCK_PAYMENTS=true` in `.env` (default in `.env.example`).
- The bot exposes a fake checkout URL and marks the payment paid after a short delay so you can test the full flow without real money.

**Real providers** — disable mock and enable only what you need (see `.env.example`):

| Provider | Enable flag | Notes |
|----------|-------------|--------|
| **Telegram Stars** | `STARS_ENABLED=true` | Inline XTR invoice; no `provider_token`; payload `{user_id}_{plan_id}` |
| **Crypto Pay** | `CRYPTOBOT_ENABLED=true` | `CRYPTOBOT_TOKEN`; webhook URL in [@CryptoBot](https://t.me/CryptoBot) → Crypto Pay → Webhooks |
| **Stripe** | `STRIPE_ENABLED=true` | `STRIPE_SECRET_KEY`, success/cancel URLs, `STRIPE_WEBHOOK_SECRET` for `/webhooks/stripe` |
| **PayPal** | `PAYPAL_ENABLED=true` | Client id/secret, return/cancel URLs, `PAYPAL_WEBHOOK_ID` for `/webhooks/paypal` |

## Commands

- `/start` — short welcome (Russian) and **reply keyboard** under the text field (Купить / Статус / Поддержка).
- `/buy` — plan → provider → pay or wait for Stars invoice (Russian UI). Same as the **Купить** menu button.
- `/status` — without arguments: **subscription** status (active until date or not found). With `<payment_id>`: payment status and provider refresh (where applicable).
- `/support` — private chat: forward messages to support recipients (see `SUPPORT_USER_IDS`).

**Admin**

- `/setplan <plan_id> <name> <price_cents> <duration_days> [stars_price]` — upsert a plan (default `stars_price` is `2600` if omitted).
- `/grant <user_id> <days>` — extend access (uses `DEFAULT_PLAN_ID` for the plan id).
- `/revoke <user_id>` — remove subscription row for that user.

## Configuration

All settings are loaded with **pydantic-settings** from `.env`. Copy `.env.example` and fill in values; secrets are never hardcoded in application code.

## Optional next steps

- Harden operational security (rate limits, idempotency keys, monitoring).
- Add renewal reminders before `active_until`.
- Add manual review or fraud rules if you scale volume.
