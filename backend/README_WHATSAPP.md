WhatsApp demo (Twilio Sandbox) — Quick setup

Overview
- This repo includes a Twilio webhook endpoint at `/api/whatsapp/webhook` that accepts incoming WhatsApp messages from Twilio Sandbox and saves them into `conversations`/`messages`.
- If you set Twilio credentials in `backend/.env` (see below), the server will reply automatically with an echo message.

Steps (local demo)
1. Install `ngrok` and run it to expose your local server:

```bash
ngrok http 8000
```

Copy the HTTPS URL (e.g. `https://abcd1234.ngrok.io`).

2. In Twilio Console -> Messaging -> Try it out -> WhatsApp Sandbox, configure the 'When a message comes in' webhook to:

```
https://<your-ngrok-host>/api/whatsapp/webhook
```

Select HTTP POST.

3. Add Twilio credentials to `backend/.env` (optional, for automated replies):

TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886  # Twilio sandbox number or your WhatsApp-enabled Twilio number

4. Start the backend server:

```powershell
Set-Location 'C:\Users\ddicicco\artigiani\backend'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

5. In your phone, join the Twilio Sandbox by following the instructions in the Twilio Console (send the join code via WhatsApp to the sandbox number).

6. Send a message from your phone to the sandbox; the server will store the message and optionally reply.

Notes
- This is a demo PoC. For production, use the official WhatsApp Business API or a paid Twilio number and secure your endpoints.
- The webhook currently assumes `business_id=1` for demo. Adjust logic in `app/routes.py` to map phone numbers to businesses.
