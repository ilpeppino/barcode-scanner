# Barcode Scanner → Google Tasks

This repository contains a small Flask application that lets you capture grocery barcodes and file them directly into Google Tasks. A desktop dashboard caters to USB “keyboard wedge” scanners, while a mobile-friendly camera UI uses the browser’s `BarcodeDetector` API for scanning on the go. The service normalizes and de-duplicates barcodes, enriches them with Open Food Facts data when available, and gives you quick visibility into recent captures.

---

## Overview

| Component | Purpose |
| --- | --- |
| `app.py` | Flask application wrapping Google Tasks integration, dedupe logic, and product lookup. |
| `static/templates/dashboard.html` & `static/js/dashboard.js` | Responsive web UI that supports desktop USB scanners and mobile browsers, with list management and recent scan log. |
| `docs/qrcodes.pdf` | Handy printable QR codes that open the dashboard on mobile devices. |

The workflow:

1. A barcode scan (desktop or mobile) posts to `/scan` with the shared ingest token.
2. The server normalizes the code, rejects duplicates within a 3‑second cooldown, and attempts an Open Food Facts lookup for title/notes enrichment.
3. A task is inserted into the active Google Tasks list, and the scan is prepended to the in-memory “Recent scans” feed.
4. The dashboard polls `/recent` and `/tasklists` to keep the UI live, and supports switching the active Google Tasks list at any time.

---

## Requirements

- Python 3.10+ (developed against 3.11).
- A Google Cloud project with the **Google Tasks API** enabled.
- An OAuth “Desktop” client downloaded as `credentials.json` in the repo root.
- Local TLS certificates if you need HTTPS for camera access (the checked-in `Giuseppes-MacBook-Air.local+1.pem` pair are machine-specific; replace as needed).
- Node.js 18+ (required when enabling Picnic cart sync).

Optional but recommended:

- A USB barcode scanner that types into focused input fields.
- A mobile browser supporting `BarcodeDetector` (recent Chrome/Safari).

---

## Quick Start

1. **Create a virtual environment (recommended).**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. **Install dependencies.**
   ```bash
   pip install -r requirements.txt
   npm install        # required if you plan to enable Picnic integration
   ```
3. **Create a `.env` file.**
   ```bash
   cp .env.example .env
   ```
   Adjust the environment variables described below.
4. **Drop your Google OAuth credentials** into `credentials.json`.
5. **Run the app.**
   ```bash
   python app.py
   ```
   On first launch the server runs the OAuth flow, writes the resulting token to `token.json`, and then listens on `https://0.0.0.0:5000/` by default. Change the `PORT` env var or the `ssl_context` tuple if required.

Once running, visit `https://<host>:<port>/` for the dashboard—which is mobile-friendly—or scan the `/docs/qrcodes.pdf` QR to open it on a phone.

---

## Configuration

All configuration comes from environment variables (e.g. `.env`). Values marked *optional* have sensible defaults.

| Key | Default | Description |
| --- | --- | --- |
| `PORT` | `5000` | Flask server port. |
| `INGEST_TOKEN` | `changeme` | Shared secret required by the `/scan` endpoint, dashboard form, and mobile UI. Choose a long random string in production. |
| `TASKLIST_ID` | *(blank)* | Preferred Google Tasks list ID. Leave blank to auto-select (or create) the first list. |
| `TASKLIST_TITLE` | *(blank)* | Friendly name used on initial dashboard load. Updated automatically when you switch lists. |
| `PICNIC_ENABLED` | *(derived)* | Set to `true`/`1` to force-enable Picnic, otherwise automatically enabled when credentials exist. |
| `PICNIC_USER` | *(blank)* | Picnic account email/username (required if no `PICNIC_AUTH_KEY`). |
| `PICNIC_PASSWORD` | *(blank)* | Picnic password (required if no `PICNIC_AUTH_KEY`). |
| `PICNIC_COUNTRY_CODE` | `NL` | Picnic country code (`NL`, `DE`, etc.). |
| `PICNIC_API_URL` | *(SDK default)* | Override Picnic API base URL if needed. |
| `PICNIC_AUTH_KEY` | *(blank)* | Pre-issued Picnic auth key; skips login when provided. |
| `PICNIC_NODE_BIN` | `node` | Path to the Node.js executable used for the Picnic helper. |


Environment changes require a server restart.

---

## Using the Application

### Desktop Dashboard (`/`)

- **Manual / USB scans** – Focus the input field, scan a barcode, and it auto-submits. Successful scans clear the field, add a task, and append to “Recent scans”.
- **Task list picker** – The “Choose list” dropdown is populated from the Google Tasks API. Switch lists any time; the selection is stored in memory and future scans go to that list.
- **Recent scans feed** – Shows timestamped entries with the resolved product title and barcode, including duplicate notices.
- **Clear list button** – Use “Clear list” in the Recent Scans card to wipe the on-screen table and the in-memory cache (useful when starting a new session).
- **Camera scanner** – Tap “Start camera” to use the device camera with the browser’s `BarcodeDetector` API (HTTPS or localhost required). Each detected barcode is sent automatically using the current ingest token.
- **Picnic cart sync** – When Picnic credentials are configured, each successful scan also adds the item to your Picnic shopping cart (via the bundled Node helper).

### API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Responsive dashboard UI (desktop and mobile). |
| `GET` | `/recent` | Returns recent scans array `{code, when}` for the dashboard table. |
| `POST` | `/scan` | Main ingest endpoint. Requires JSON body `{"code": "...", "token": "..."}` or `X-Ingest-Token` header. |
| `GET` | `/tasklists` | Lists available Google Tasks lists (`id`, `title`) and the currently selected list ID. |
| `POST` | `/tasklists/select` | Switches the active Google Tasks list. JSON body: `{"tasklist_id": "..."}`. |
| `POST` | `/recent/clear` | Clears the in-memory recent scan cache and duplicate tracker. |

All responses are JSON except for the templated pages. Non-200 responses from `/scan` include an explanatory message that surfaces in the UI banner.

---

## Behavior Details

- **Barcode normalization** – Non-digits are stripped; 12-digit UPC-A codes are zero-padded to 13 digits to align with EAN-13.
- **Duplicate suppression** – Scans of the same normalized code within 3 seconds are ignored, but still logged with a “dup ignored” marker for operator feedback.
- **Recent cache** – The in-memory log stores both product title and barcode; clearing it via the dashboard also resets the duplicate detector.
- **Product enrichment** – The server attempts an Open Food Facts lookup to populate the Google Task title and optional notes (brand, quantity, categories, image). Failures fall back to using the raw code without raising errors.
- **Google Tasks integration** – Tokens are refreshed automatically when expired. If a task insertion fails (e.g., revoked authorization), the `/scan` endpoint returns an error so the operator can re-authenticate.
- **Camera mode** – Uses `navigator.mediaDevices.getUserMedia` plus the `BarcodeDetector` API. Browsers must run on HTTPS (or localhost) and support the API to stream scans.
- **Picnic integration** – `picnic_client.mjs` (Node.js) handles login/search/cart additions. Keep credentials in environment variables and ensure Node is available in the runtime/container.
- **Port freeing** – On macOS/Linux the app calls `lsof` to free the configured port before starting, which helps during development restarts.

---

## Development Notes

- Delete `token.json` if you need to re-run the OAuth flow with a different Google account or scopes.
- Update `ssl_context` in `app.py` if you replace certificates or switch to HTTP in a trusted network.
- `barcode_favicon.ico` can be served by dropping it into your preferred static file pipeline if you expose favicons.
- `picnic_client.mjs` is invoked by the Flask app; keep Node.js available (and run `npm install`) in any deployment image where Picnic sync is enabled.

---

## Troubleshooting

- **“Auth failed” in logs or UI** – Ensure the ingest token in `.env`, the dashboard input, and the mobile token all match exactly.
- **Tasks no longer appear** – Revoked credentials cause `/scan` to emit an error banner. Delete `token.json` and restart to trigger OAuth; also confirm the selected list still exists.
- **Mobile camera won’t start** – The device must load the page over HTTPS; use the provided TLS certs or set up your own trusted cert.
- **Camera button disabled or errors** – Modern Chrome/Safari builds on HTTPS (or localhost) are required for `BarcodeDetector`. If unsupported, use the manual field or a USB scanner instead.
- **Picnic add failed** – Check that Node is installed, the helper (`picnic_client.mjs`) exists, and environment variables (`PICNIC_USER`/`PICNIC_PASSWORD` or `PICNIC_AUTH_KEY`) are configured. Failure messages show up in the dashboard banner and server logs.

With this README you should have all the context necessary to reason about the app’s behavior, extend it, or troubleshoot scanning issues during future sessions.
