# Barcode Scanner → Google Tasks

A small Flask application that lets you point any camera (desktop or phone) at groceries, read the barcode or run OCR on labels/receipts, and drop everything directly into Google Tasks. The dashboard is responsive, supports real-time recent history, and runs happily on laptops, desktops, or a NAS container.

---

## What You Get

| Component | Description |
| --- | --- |
| `app.py` | Flask + Gunicorn backend. Handles Google Tasks OAuth, barcode dedupe, OCR routing (pytesseract), Open Food Facts enrichment, and REST endpoints. |
| `static/templates/dashboard.html` | Unified HTML/JS dashboard: USB scanners, auto barcode capture, OCR capture, recent history, task-list switcher. |
| `docs/qrcodes.pdf` | Printable QR codes to open the dashboard from your phone. |

Workflow:

1. You authenticate once with Google Tasks (Desktop OAuth client).  
2. The dashboard auto-starts your camera (HTTPS context) and continuously listens for barcodes or on-demand OCR captures.  
3. Each barcode is normalized, de-duplicated (3 s cooldown), optionally enriched with Open Food Facts, and inserted into your selected Google Tasks list.  
4. OCR captures route through pytesseract and the extracted text is shown immediately in the UI for easy copy/paste.  
5. Recent scans + OCR updates refresh automatically so operators always see what just went in.

---

## Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.10+ (for local dev) | Repo tested with 3.11. |
| Tesseract OCR binary | `brew install tesseract` (macOS) / `apt install tesseract-ocr` (Debian/Ubuntu). Needed even in Docker builds. |
| Google Cloud project | Enable **Google Tasks API**, create an OAuth *Web application* client, add redirect URIs, and paste the Client ID/secret into `.env`. |
| HTTPS access for cameras | Browsers only grant camera access on HTTPS or `localhost`. For WAN/LAN access use Cloudflare, Let’s Encrypt, mkcert, etc. |
| Domain/DNS (optional but recommended) | Example: `gtemp1.com` on Hostinger with Cloudflare proxying to your NAS. |

Optional tooling: Docker & Docker Compose (for NAS/Synology), Cloudflare Tunnel/Access, Pi-hole for LAN DNS.

### Python modules

If you install dependencies manually (outside Docker), ensure these packages are present:

```
Flask==3.0.3
google-api-python-client==2.149.0
google-auth==2.35.0
google-auth-oauthlib==1.2.1
google-auth-httplib2==0.2.0
requests==2.32.3
python-dotenv==1.0.1
gunicorn
pytesseract==0.3.10
Pillow==11.0.0
```

Running `pip install -r requirements.txt` installs the exact versions above.


---

## Local Development (macOS/Linux/WSL)

1. **Clone & enter repo**
   ```bash
   git clone https://github.com/<you>/barcode-scanner.git
   cd barcode-scanner
   ```
2. **Virtualenv + deps**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Configure env**
   ```bash
   cp .env.example .env
   # edit PORT, TASKLIST_TITLE, etc.
   ```
4. **Configure OAuth + secrets**
   ```bash
   cp .env.example .env
   # fill FLASK_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, etc.
   ```
5. **Start dev server**
   ```bash
   python app.py
   ```
   Flask runs with the bundled TLS cert (`Giuseppes-*.pem`). Swap in your own PEM pair (mkcert works) via the `ssl_context` tuple if needed.
6. **Open dashboard**
   - Desktop: `https://127.0.0.1:5000/`  
   - Phone on same LAN: trust the cert (mkcert CA) or proxy via Cloudflare/HTTPS.

---

## Google OAuth – Step-by-step

1. In Google Cloud Console → APIs & Services → Enable APIs → **Google Tasks API**.
2. Configure the OAuth consent screen (External), add yourself to “Test users”, and save.
3. Credentials → Create Credentials → *OAuth client ID* → Application type **Web application**.
4. Add Authorized redirect URIs for every environment you plan to run (e.g. `https://localhost:5000/auth/callback`, `https://scanner.gtemp1.com/auth/callback`).
5. Copy the Client ID/secret into `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`). If you need a fixed callback (e.g. behind Cloudflare), set `GOOGLE_AUTH_REDIRECT_URI`.
6. Start the app and visit `/login` — users authenticate in the browser, and the token is stored in their session automatically.

---

## Production Deployment (Docker)

Build and push a multi-arch image to GHCR (replace `<user>` and version):

```bash
cd ~/dev/barcode-scanner-clean
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/<user>/barcode-scanner:v1.4.0 \
  -t ghcr.io/<user>/barcode-scanner:stable \
  --push .
```

Example `docker-compose.yml` (Cloudflare terminates HTTPS, container serves HTTP on 5000):

```yaml
version: "3.8"
services:
  scanner:
    image: ghcr.io/<user>/barcode-scanner:stable
    restart: unless-stopped
    env_file:
      - ./.env
    ports:
      - "5050:5000"        # NAS:5050 → container:5000
```

Deploy / upgrade:

```bash
docker compose down
docker compose pull scanner
docker compose up -d
```

### TLS options

1. **Cloudflare (recommended)**
   - Keep container on HTTP (port 5000).  
   - Proxy `scanner.gtemp1.com` ➜ `http://NAS-IP:5050`.  
   - Use Cloudflare Access for optional auth, caching, WAF.  
   - Result: browser sees HTTPS, container stays simple.

2. **mkcert for LAN testing**
   - `mkcert <nas-hostname>`  
   - Install mkcert CA on iOS/Android for trusted HTTPS over LAN, then front the container with nginx/traefik locally if you need HTTPS.

---

## Camera Requirements & Modes

- Barcode mode uses the browser’s `BarcodeDetector` API. Unsupported browsers (older Safari) automatically fall back to OCR mode only.
- OCR mode leverages pytesseract; the dashboard preprocesses captures (grayscale + contrast) before uploading to `/ocr`.
- **HTTPS is mandatory** for mobile camera use. For WAN, proxy through Cloudflare/Let’s Encrypt. For LAN, trust mkcert or run via `ngrok`/Cloudflare Tunnel.

---

## Maintenance

| Task | Notes |
| --- | --- |
| Rotate Google OAuth client | Update `GOOGLE_CLIENT_ID/SECRET`, redeploy, and users will be prompted to sign in again. |
| Update certs | If Cloudflare terminates HTTPS, handled automatically. For direct TLS (Let’s Encrypt/Hostinger), renew and copy new cert/key into `certs/`. |
| Upgrades | `git pull`, rebuild image, `docker compose up -d --build`. |
| Logs | `docker compose logs -f scanner`. |

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| **Camera idle / blocked** | Ensure page loads via HTTPS. On iOS, user gesture (Enable Camera button) is required if auto-start fails. Cloudflare HTTPS works out of the box. |
| **Barcode mode disabled** | Browser lacks `BarcodeDetector` (older Safari). OCR mode still works; for live barcodes use desktop Chrome or implement QuaggaJS. |
| **Tasks fail to create** | User session expired or Google revoked access → hit **Logout** and sign in again. Ensure Google Tasks API is enabled. |
| **Open Food Facts slow** | API is best-effort. Network failures fall back to barcode-as-title automatically. |

---

## Directory Layout (key files)

```
.
├─ app.py                 # Flask app / endpoints
├─ static/templates/
│   └── dashboard.html    # Single-page dashboard (JS inline)
├─ docs/qrcodes.pdf
├─ certs/                 # TLS certs for dev or direct TLS builds
├─ .env.example           # sample config (FLASK_SECRET, Google OAuth, etc.)
├─ dockerfile
├─ docker-compose.yml     # sample compose (if using Docker)
└─ NAS.md                 # Synology deployment notes
```

---

Happy scanning! Adjust the dashboard styles, integrate QuaggaJS, or bolt on additional storage (Notion, Sheets) as needed.
