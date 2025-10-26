# Barcode Scanner → Google Tasks

A small Flask app that receives barcode scans, de-duplicates them, looks up friendly product info, and pushes the result into Google Tasks. It includes both a desktop dashboard (for USB scanners) and a mobile camera UI (using the browser’s `BarcodeDetector` API).

## Features
- Accepts scans from a USB keyboard-style scanner or a phone camera at `/mobile`.
- Adds each scan to the Google Task list you choose, including basic product details via Open Food Facts when available.
- Rejects repeated scans that happen inside a short cooldown window.
- Shows a rolling log of recent scans at `/`.

## Prerequisites
- Python 3.10+ (developed against 3.11).
- A Google Cloud project with the Google Tasks API enabled.
- An OAuth client (Desktop type) downloaded as `credentials.json` in the project root.
- Local TLS certificates so browsers allow the mobile camera (`Giuseppes-MacBook-Air.local+1.pem` and `Giuseppes-MacBook-Air.local+1-key.pem` are included for the original machine; replace with your own if needed).

## Setup
1. Create and activate a virtual environment (recommended):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file to supply runtime configuration:
   ```bash
   cp .env.example .env  # if you have one, otherwise create manually
   ```
   Minimum keys:
   ```
   INGEST_TOKEN=choose-a-long-random-string
   PORT=5000
   TASKLIST_ID=  # optional; leave blank to use the first Tasks list
   TASKLIST_TITLE=Groceries  # optional label used on the UI
   ```
   - `INGEST_TOKEN` secures the `/scan` endpoint; the mobile UI and manual form must send the same value.
   - `TASKLIST_ID` is optional; the app will create or reuse the first task list if left blank.
4. Place the Google OAuth client JSON as `credentials.json` in the repo root. The first run will launch a browser window so you can authorize the app; it caches tokens in `token.json`.

## Running the server
```bash
python app.py
```

By default the app listens on `https://0.0.0.0:5000/` with the TLS certificate referenced in `app.py`. Adjust `PORT` and/or the `ssl_context` tuple if you are using different certificates or prefer plain HTTP (only advisable for trusted local networks).

## Using the app
- Visit `https://<host>:<port>/` for the dashboard. You can type or scan codes into the form; each successful scan appears under “Recent scans”.
- Visit `https://<host>:<port>/mobile` on a phone. Enter the `INGEST_TOKEN` once and keep the page open to scan items with the device camera. (Modern Chrome/Safari required; HTTPS is mandatory for camera access.)
- The `/scan` endpoint also accepts JSON `{"code": "...", "token": "..."}` so you can integrate other scanners or scripts.
- The `/recent` endpoint returns the latest 200 scans as JSON for debugging.

## Development tips
- When changing the Google account or scopes, delete `token.json` to trigger a fresh OAuth flow.
- If you replace certificates, update the filenames referenced at the bottom of `app.py`.
- The Open Food Facts lookup is best-effort; if the API call fails, the task will simply use the raw barcode.
