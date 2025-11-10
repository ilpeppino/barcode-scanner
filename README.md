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

1. A barcode scan (desktop or mobile) posts to `/scan` directly from the unified camera UI.
2. The server normalizes the code, rejects duplicates within a 3‑second cooldown, and attempts an Open Food Facts lookup for title/notes enrichment.
3. A task is inserted into the active Google Tasks list, and the scan is prepended to the in-memory “Recent scans” feed.
4. The dashboard polls `/recent` and `/tasklists` to keep the UI live, and supports switching the active Google Tasks list at any time.

## Features

- **Instant Google Tasks sync** – Every barcode becomes a new task (with optional product metadata) on the selected list.
- **Dual input modes** – Works with USB “keyboard wedge” scanners or the built-in camera scanner (modern HTTPS browsers required).
- **Recent activity board** – Shows timestamps, resolved titles, and barcodes for the last 200 scans plus duplicate warnings.
- **Task list selector** – Choose a default list at runtime without editing environment variables.
- **Mobile-friendly UI** – Responsive layout adapts to phones/tablets for pantry-side scanning.
- **Image OCR uploads** – Drag-and-drop a label/receipt photo and extract text through Tesseract right from the dashboard.
- **Unified camera workflow** – The app auto-starts the camera and uses a single capture button for both barcode scans and document OCR, mirroring the new dashboard mockups.

---

## Requirements

- Python 3.10+ (developed against 3.11).
- A Google Cloud project with the **Google Tasks API** enabled.
- An OAuth “Desktop” client downloaded as `credentials.json` in the repo root.
- Local TLS certificates if you need HTTPS for camera access (the checked-in `Giuseppes-MacBook-Air.local+1.pem` pair are machine-specific; replace as needed).
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on the host (`brew install tesseract` on macOS, `apt install tesseract-ocr` on Debian/Ubuntu) for the OCR endpoint.

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
| `TASKLIST_ID` | *(blank)* | Preferred Google Tasks list ID. Leave blank to auto-select (or create) the first list. |
| `TASKLIST_TITLE` | *(blank)* | Friendly name used on initial dashboard load. Updated automatically when you switch lists. |


Environment changes require a server restart.

---

## Using the Application

### Desktop Dashboard (`/`)

- **Unified camera hero** – The app auto-starts your camera (HTTPS required) and exposes a single capture button that adapts to the selected mode.
- **Scanner mode selector** – Toggle between “Barcode Scanner” (sends the next capture to `/scan`) and “Document OCR” (sends the frame to `/ocr`).
- **Recent scans feed** – Shows timestamped entries with the resolved product title and barcode, including duplicate notices. The feed refreshes automatically after every successful barcode capture.
- **Extracted text panel** – Displays the most recent OCR output from the camera. Each new document capture replaces the text and keeps the historical log in the textarea for copy/paste.
- **Clear list button** – Use “Clear list” in the Recent Scans card to wipe the on-screen table and the in-memory cache (useful when starting a new session).

### API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Responsive dashboard UI (desktop and mobile). |
| `GET` | `/recent` | Returns recent scans array `{code, when}` for the dashboard table. |
| `POST` | `/scan` | Main ingest endpoint. Send JSON body `{"code": "..."}`. |
| `GET` | `/tasklists` | Lists available Google Tasks lists (`id`, `title`) and the currently selected list ID. |
| `POST` | `/tasklists/select` | Switches the active Google Tasks list. JSON body: `{"tasklist_id": "..."}`. |
| `POST` | `/recent/clear` | Clears the in-memory recent scan cache and duplicate tracker. |
| `POST` | `/ocr` | Accepts `multipart/form-data` with `image` (and optional `language`). Returns extracted text via Tesseract. |

All responses are JSON except for the templated pages. Non-200 responses from `/scan` include an explanatory message that surfaces in the UI banner.

Example OCR request:

```bash
curl -X POST https://localhost:5000/ocr \
  -F image=@label.jpg \
  -F language=eng
```

Response:

```json
{ "ok": true, "text": "Recognized characters...", "language": "eng" }
```

---

## Behavior Details

- **Barcode normalization** – Non-digits are stripped; 12-digit UPC-A codes are zero-padded to 13 digits to align with EAN-13.
- **Duplicate suppression** – Scans of the same normalized code within 3 seconds are ignored, but still logged with a “dup ignored” marker for operator feedback.
- **Recent cache** – The in-memory log stores both product title and barcode; clearing it via the dashboard also resets the duplicate detector.
- **Product enrichment** – The server attempts an Open Food Facts lookup to populate the Google Task title and optional notes (brand, quantity, categories, image). Failures fall back to using the raw code without raising errors.
- **Google Tasks integration** – Tokens are refreshed automatically when expired. If a task insertion fails (e.g., revoked authorization), the `/scan` endpoint returns an error so the operator can re-authenticate.
- **Camera mode** – Uses `navigator.mediaDevices.getUserMedia` plus the `BarcodeDetector` API. Browsers must run on HTTPS (or localhost) and support the API to stream scans.
- **Port freeing** – On macOS/Linux the app calls `lsof` to free the configured port before starting, which helps during development restarts.

---

## Development Notes

- Delete `token.json` if you need to re-run the OAuth flow with a different Google account or scopes.
- Update `ssl_context` in `app.py` if you replace certificates or switch to HTTP in a trusted network.
- `barcode_favicon.ico` can be served by dropping it into your preferred static file pipeline if you expose favicons.

---

## Troubleshooting

- **Tasks no longer appear** – Revoked credentials cause `/scan` to emit an error banner. Delete `token.json` and restart to trigger OAuth; also confirm the selected list still exists.
- **Mobile camera won’t start** – The device must load the page over HTTPS; use the provided TLS certs or set up your own trusted cert.
- **Camera button disabled or errors** – Modern Chrome/Safari builds on HTTPS (or localhost) are required for `BarcodeDetector`. If unsupported, use the manual field or a USB scanner instead.


---

## Android Camera Setup and HTTPS Trust Configuration

Modern mobile browsers require HTTPS to access the camera via the `getUserMedia` API (used by the barcode scanner UI). If you use a self-signed certificate (such as one generated by [mkcert](https://github.com/FiloSottile/mkcert)), Android devices will reject the connection unless you explicitly trust the mkcert CA root. This section explains how to install and trust the mkcert CA on Android so you can scan barcodes securely with your phone's camera.

### Why HTTPS is Required

The browser’s `getUserMedia` API—which powers the camera barcode scanner—**only works on HTTPS origins** (or `localhost`). This is a security restriction in all modern browsers to prevent unauthorized camera access. If you want to use your phone or tablet as a scanner on your local network, you must serve the app over HTTPS and ensure the certificate is trusted by your device.

### Finding the mkcert CA Root Certificate

On your development machine, locate the mkcert CA root certificate:

```bash
mkcert -CAROOT
```

This prints the directory where mkcert stores its root CA. Inside, you’ll find a file named `rootCA.pem`. This is the certificate you need to install on your Android device.

### Copying `rootCA.pem` to Android

1. Copy the `rootCA.pem` file from your computer to your Android device. You can use email, cloud storage, Airdrop (on supported devices), or a USB cable.
2. Make sure the file is accessible in your Android device’s Downloads or Files app.

### Installing the CA Certificate on Android

1. Open **Settings** on your Android device.
2. Go to **Security & privacy**.
3. Select **Encryption & credentials** (the name may vary by Android version).
4. Tap **Install a certificate**.
5. Choose **CA certificate**.
6. When prompted, select the `rootCA.pem` file you copied.
7. Confirm installation when prompted.

After completing these steps, Android will trust all certificates issued by your mkcert CA—including the self-signed HTTPS certificate used by your Flask app (e.g., `https://192.168.178.45:5050` or any other local NAS/dev host URL).

### Using the Barcode Scanner Web App

Once the mkcert CA is installed and trusted:

- You can open the barcode scanner web app on your Android device using HTTPS.
- The browser will no longer show certificate warnings.
- You can grant camera permissions and use the scanning UI without errors.

> **Note:** Only install CA certificates that you generated yourself on your own machine using mkcert. **Never install untrusted CA files** or certificates from unknown sources, as this can compromise your device's security.
