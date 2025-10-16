import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, abort
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

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
    # run local OAuth flow
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
  const tokenInput = document.getElementById('token');
  const v = document.getElementById('v');
  const status = document.getElementById('status');

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      v.srcObject = stream;
      await v.play();
      if (!('BarcodeDetector' in window)) {
        status.innerHTML = '<p class="err">BarcodeDetector not supported. Use Chrome or Safari.</p>';
        return;
      }
      const det = new BarcodeDetector({ formats: ['ean_13','ean_8','code_128','code_39','qr_code','upc_a','upc_e','itf'] });
      const seen = new Set();
      async function tick() {
        try {
          const barcodes = await det.detect(v);
          for (const b of barcodes) {
            const code = b.rawValue.trim();
            if (code && !seen.has(code)) {
              seen.add(code);
              const r = await fetch('/scan', { method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({ code, token: tokenInput.value.trim() }) });
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
    if data.get("token") != INGEST_TOKEN:
        abort(401)
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "message": "Missing code"}), 400
    create_task(title=code)
    log_scan(code)
    return jsonify({"ok": True, "message": f"Added task: {code}"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)