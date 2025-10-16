import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, abort
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import time
import re
import requests

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/tasks"]
PORT = int(os.getenv("PORT", "5000"))
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "changeme")
TASKLIST_ID = os.getenv("TASKLIST_ID", "").strip()

app = Flask(__name__)

# ---------- Google Tasks helpers ----------
def get_creds():
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        if creds and creds.valid:
            return creds
    # Run OAuth flow if no valid token found
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "w") as f:
        f.write(creds.to_json())
    return creds


def get_tasks_service():
    creds = get_creds()
    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def ensure_tasklist_id(service):
    global TASKLIST_ID
    if TASKLIST_ID:
        return TASKLIST_ID
    lists = service.tasklists().list(maxResults=10).execute()
    if "items" in lists and lists["items"]:
        TASKLIST_ID = lists["items"][0]["id"]
        return TASKLIST_ID
    created = service.tasklists().insert(body={"title": "Tasks"}).execute()
    TASKLIST_ID = created["id"]
    return TASKLIST_ID


def create_task(title, notes=None):
    service = get_tasks_service()
    tl_id = ensure_tasklist_id(service)
    body = {"title": title}
    if notes:
        body["notes"] = notes
    return service.tasks().insert(tasklist=tl_id, body=body).execute()


# ---------- Barcode normalization, dedupe, and product lookup ----------

def normalize_barcode(raw: str) -> str:
    """Strip non-digits; convert 12-digit UPC-A to 13-digit EAN-13 by padding leading 0."""
    digits = re.sub(r"\D+", "", raw or "")
    if len(digits) == 12:  # UPC-A
        return "0" + digits  # as EAN-13
    return digits or (raw or "").strip()

# cooldown memory to prevent duplicate inserts within a short window
LAST_SEEN = {}  # code -> last_timestamp
COOLDOWN_SEC = 3.0

def is_recent_duplicate(code: str) -> bool:
    now = time.time()
    ts = LAST_SEEN.get(code, 0)
    if now - ts < COOLDOWN_SEC:
        return True
    LAST_SEEN[code] = now
    # light pruning
    if len(LAST_SEEN) > 1000:
        cutoff = now - COOLDOWN_SEC
        for k in list(LAST_SEEN.keys()):
            if LAST_SEEN[k] < cutoff:
                LAST_SEEN.pop(k, None)
    return False

def lookup_product_title_notes(code: str):
    """
    Try Open Food Facts for a human-friendly name.
    Returns (title, notes). Fallback to code as title.
    """
    try:
        r = requests.get(f"https://world.openfoodfacts.org/api/v2/product/{code}.json", timeout=3)
        if r.ok:
            j = r.json()
            if j.get("status") == 1:
                p = j.get("product", {})
                name = (p.get("product_name") or "").strip()
                brand = (p.get("brands") or "").split(",")[0].strip()
                title = " - ".join(x for x in [brand or None, name or None] if x) or code
                notes = f"Barcode: {code}"
                if p.get("quantity"):
                    notes += f"\nQuantity: {p['quantity']}"
                if p.get("categories"):
                    notes += f"\nCategories: {p['categories']}"
                if p.get("image_url"):
                    notes += f"\nImage: {p['image_url']}"
                return title, notes
    except Exception:
        pass
    return code, None

# ---------- Simple in-memory log ----------
RECENT = []  # list of dicts {code, when}


def log_scan(code):
    RECENT.insert(0, {"code": code, "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    del RECENT[200:]  # keep last 200


# ---------- Routes ----------

DASHBOARD_HTML = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Barcode → Google Tasks</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 20px; }
    h1 { margin: 0 0 10px; }
    .row { display: flex; gap: 1rem; flex-wrap: wrap; }
    .card { border: 1px solid #ddd; border-radius: 12px; padding: 16px; min-width: 280px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border-bottom: 1px solid #eee; padding: 8px; text-align: left; }
    code { background: #f6f8fa; padding: 2px 4px; border-radius: 6px; }
    .muted { color: #666; font-size: 0.9em; }
    input, button { padding: 8px 10px; }
  </style>
</head>
<body>
  <h1>Barcode → Google Tasks</h1>
  <div class="row">
    <div class="card">
      <h3>Quick manual entry (testing)</h3>
      <form id="f">
        <input id="code" placeholder="Type or scan here" autofocus />
        <input id="token" placeholder="INGEST_TOKEN" />
        <button>Add</button>
      </form>
      <p class="muted">Use your USB scanner here — it types like a keyboard and hits Enter.</p>
      <div id="msg"></div>
    </div>
    <div class="card">
      <h3>Use phone camera</h3>
      <p>Open on your phone: <code>/mobile</code></p>
      <p class="muted">Phone scans code and POSTs here. Set <code>INGEST_TOKEN</code> in .env.</p>
    </div>
  </div>
  <div class="card" style="margin-top:1rem;">
    <h3>Recent scans</h3>
    <table id="t"><thead><tr><th>When</th><th>Code</th></tr></thead><tbody></tbody></table>
  </div>
<script>
  const f = document.getElementById('f');
  const code = document.getElementById('code');
  const token = document.getElementById('token');
  const msg = document.getElementById('msg');
  const tbody = document.querySelector('#t tbody');

  async function refresh() {
    const r = await fetch('/recent');
    const data = await r.json();
    tbody.innerHTML = data.map(x => `<tr><td>${x.when}</td><td>${x.code}</td></tr>`).join('');
  }
  setInterval(refresh, 1500);
  refresh();

  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = { code: code.value.trim(), token: token.value.trim() };
    const r = await fetch('/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const j = await r.json();
    msg.textContent = j.message || JSON.stringify(j);
    code.value = '';
    code.focus();
    refresh();
  });
</script>
</body>
</html>
"""

MOBILE_HTML = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Phone Scanner</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 16px; }
    video { width: 100%; max-width: 520px; border-radius: 12px; }
    input, button { padding: 10px 12px; margin: 6px 0; width: 100%; }
    .card { border: 1px solid #ddd; border-radius: 12px; padding: 16px; }
    .ok { color: #1a7f37; } .err { color: #b80000; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Scan with phone camera</h2>
    <input id="token" placeholder="INGEST_TOKEN" />
    <video id="v" playsinline></video>
    <div id="status"></div>
  </div>
<script type="module">
  // Check if getUserMedia exists (HTTPS required on mobile)
  if (!("mediaDevices" in navigator) || !("getUserMedia" in navigator.mediaDevices)) {
    const host = location.host;
    document.write('<p class="err">Camera API not available. On mobile, this usually means the page is not opened over HTTPS. Try: <strong>https://' + host + '/mobile</strong>. On iOS, Chrome and Safari both require HTTPS for camera access.</p>');
    throw new Error('getUserMedia unavailable');
  }

  const tokenInput = document.getElementById('token');
  const v = document.getElementById('v');
  const status = document.getElementById('status');

  // Persist token locally on the device
  tokenInput.value = localStorage.getItem('ingestToken') || '';
  tokenInput.addEventListener('change', () => localStorage.setItem('ingestToken', tokenInput.value.trim()));

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      v.srcObject = stream;
      await v.play();
      if (!('BarcodeDetector' in window)) {
        status.innerHTML = '<p class="err">BarcodeDetector not supported. Use Chrome or Safari.</p>';
        return;
      }
      const det = new BarcodeDetector({ formats: ['ean_13','ean_8','code_128','code_39','qr_code','itf'] });
      const seen = new Set();
      async function tick() {
        try {
          const barcodes = await det.detect(v);
          for (const b of barcodes) {
            const code = b.rawValue.trim();
            if (code && !seen.has(code)) {
              seen.add(code);
              const token = tokenInput.value.trim();
              const r = await fetch('/scan', {
                method:'POST',
                headers:{
                  'Content-Type':'application/json',
                  'X-Ingest-Token': token
                },
                body: JSON.stringify({ code, token })
              });
              const j = await r.json();
              status.innerHTML = `<p class="${r.ok?'ok':'err'}">${j.message || JSON.stringify(j)}</p>`;
            }
          }
        } catch(e) {}
        requestAnimationFrame(tick);
      }
      tick();
    } catch (e) {
      status.innerHTML = `<p class="err">${e.message}</p>`;
    }
  }
  start();
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(DASHBOARD_HTML)

@app.route("/mobile")
def mobile():
    return render_template_string(MOBILE_HTML)

@app.route("/recent")
def recent():
    return jsonify(RECENT)

@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}
    # Accept token from JSON body, header, or query param for convenience
    token = data.get("token") or request.headers.get("X-Ingest-Token") or request.args.get("token")
    if token != INGEST_TOKEN:
        logger.info("Auth failed from %s: provided token len=%s (expected non-empty). Hint: set INGEST_TOKEN in .env and enter same on /mobile.", request.remote_addr, len(token) if token else 0)
        abort(401)

    raw = (data.get("code") or "").strip()
    logger.info("Received scan request from %s: %s", request.remote_addr, raw)
    if not raw:
        return jsonify({"ok": False, "message": "Missing code"}), 400

    code = normalize_barcode(raw)
    if is_recent_duplicate(code):
        logger.info("Duplicate detected for code %s - ignoring", code)
        log_scan(code + " (dup ignored)")
        return jsonify({"ok": True, "message": f"Ignored duplicate: {code}"}), 200

    title, notes = lookup_product_title_notes(code)
    logger.info("Creating task for code %s with title '%s'", code, title)
    create_task(title=title, notes=notes)
    logger.info("Task created successfully for %s", code)
    log_scan(code)
    return jsonify({"ok": True, "message": f"Added task: {title}"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True, ssl_context=("Giuseppes-MacBook-Air.local+1.pem", "Giuseppes-MacBook-Air.local+1-key.pem"))