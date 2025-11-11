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
| Google Cloud project | Enable **Google Tasks API**, create an OAuth *Desktop app* client, download `credentials.json`. |
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
4. **Drop Google OAuth files**
   - `credentials.json` → repo root.  
   - First run will produce `token.json` (store it; delete to re-auth).
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
2. Credentials → Create Credentials → *OAuth client ID* → Application type **Desktop**.
3. Download the JSON, rename to `credentials.json`, place in repo root.
4. Run `python app.py` once; browser opens Google consent. Complete flow → `token.json` is generated.
5. Protect `credentials.json`/`token.json` (never commit them). In Docker, map them via volumes.

---

## Production Deployment (Docker)

You can build locally or on your NAS:

```bash
# from repo root
docker build -t barcode-scanner:latest .
```

Example `docker-compose.yml` (Cloudflare terminates HTTPS, container serves HTTP on 5000):

```yaml
version: "3.8"
services:
  scanner:
    image: barcode-scanner:latest
    restart: unless-stopped
    ports:
      - "5050:5000"        # NAS:5050 → container:5000
    environment:
      PORT: "5000"
      IMAGE_TAG: "${IMAGE_TAG:-dev}"
    volumes:
      - ./credentials.json:/app/credentials.json:ro
      - ./token.json:/app/token.json
      - ./certs:/app/certs               # optional if you terminate TLS inside
```

Run/recreate:

```bash
docker compose down
docker compose up -d --build
```

### TLS options

1. **Cloudflare (recommended)**
   - Keep container on HTTP (port 5000).  
   - Proxy `scanner.gtemp1.com` ➜ `http://NAS-IP:5050`.  
   - Use Cloudflare Access for optional auth, caching, WAF.  
   - Result: browser sees HTTPS, container stays simple.

2. **Direct TLS**
   - Obtain cert/key (`Let’s Encrypt`, Hostinger SSL manager, mkcert).  
   - Place as `certs/dsplay418.crt` + `certs/dsplay418.key`.  
   - Container already launches gunicorn with `--certfile/--keyfile`; just mount the files read-only.

3. **mkcert for LAN testing**
   - `mkcert <nas-hostname>`  
   - Install mkcert CA on iOS/Android for trusted HTTPS over LAN.

---

## Camera Requirements & Modes

- Barcode mode uses the browser’s `BarcodeDetector` API. Unsupported browsers (older Safari) automatically fall back to OCR mode only.
- OCR mode leverages pytesseract; the dashboard preprocesses captures (grayscale + contrast) before uploading to `/ocr`.
- **HTTPS is mandatory** for mobile camera use. For WAN, proxy through Cloudflare/Let’s Encrypt. For LAN, trust mkcert or run via `ngrok`/Cloudflare Tunnel.

---

## Maintenance

| Task | Notes |
| --- | --- |
| Rotate Google tokens | Delete `token.json` and restart to re-auth. |
| Update certs | If Cloudflare terminates HTTPS, handled automatically. For direct TLS (Let’s Encrypt/Hostinger), renew and copy new cert/key into `certs/`. |
| Upgrades | `git pull`, rebuild image, `docker compose up -d --build`. |
| Logs | `docker compose logs -f scanner`. |

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| **Camera idle / blocked** | Ensure page loads via HTTPS. On iOS, user gesture (Enable Camera button) is required if auto-start fails. Cloudflare HTTPS works out of the box. |
| **Barcode mode disabled** | Browser lacks `BarcodeDetector` (older Safari). OCR mode still works; for live barcodes use desktop Chrome or implement QuaggaJS. |
| **Tasks fail to create** | OAuth token expired or revoked → delete `token.json` and restart. Ensure Google Tasks API enabled. |
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
├─ credentials.json       # Google OAuth client (not committed)
├─ token.json             # OAuth tokens (not committed)
├─ dockerfile
├─ docker-compose.yml     # sample compose (if using Docker)
└─ NAS.md                 # Synology deployment notes
```

---

Happy scanning! Adjust the dashboard styles, integrate QuaggaJS, or bolt on additional storage (Notion, Sheets) as needed.
