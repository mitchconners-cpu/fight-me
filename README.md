# BTC Wager Gateway

SMS + web console for creating and settling peer-to-peer wagers, with a
Bitcoin address as the unified user identity across both channels.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env: PROJECT_CRYPTO_SALT, TWILIO_AUTH_TOKEN, wallet addresses
```

Generate a salt:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Running

```bash
uvicorn gateway_app:app --reload --port 8000
```

Web console: http://127.0.0.1:8000/console

## Local SMS testing (no Twilio account needed)

```bash
# Terminal 1
uvicorn gateway_app:app --reload --port 8000

# Terminal 2 -- mock gateway that prints outbound replies instead of texting
python local_twilio.py serve

# Terminal 3 -- simulate inbound texts
python local_twilio.py text +15555550123 "REGISTER bc1qexampleaddressxxxxxxxxxxxxxxxxxxxxxxxx"
python local_twilio.py text +15555550123 "HELP"
python local_twilio.py text +15555550123 "BET 50 cash Team A wins Sunday"
```

Set `ANDROID_GATEWAY_URL=http://127.0.0.1:8081/send` in `.env` so replies
route to the mock gateway.

## Going live with real Twilio

1. Set `TWILIO_AUTH_TOKEN` in `.env` -- without it, webhook signature
   validation is disabled and a warning prints on every request.
2. Point your Twilio phone number's inbound webhook at
   `POST https://your-domain/webhook/twilio-sms`.

## Project layout

See `notes/architecture_notes.md` for the identity model, bet lifecycle,
and full SMS command reference.

## Before handling real funds

This is a functional prototype, not a production money-handling system.
At minimum, before real Bitcoin is involved:

- Legal/licensing review for your target jurisdiction (this is gambling +
  money transmission in most places; requirements vary a lot by country).
- Real on-chain funding verification (own node/indexer, not a public
  explorer) with per-bet or per-user deposit addresses.
- An admin/ops path for disputes, refunds, and auditing.
