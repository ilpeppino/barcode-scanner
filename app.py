import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, abort
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import time
import re
import requests
import signal
import subprocess

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/tasks"]
PORT = int(os.getenv("PORT", "5000"))
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "changeme")
TASKLIST_ID = os.getenv("TASKLIST_ID", "").strip()
TASKLIST_TITLE = os.getenv("TASKLIST_TITLE", "").strip()

# Tell Flask where the Jinja templates actually live (they're under static/templates).
app = Flask(__name__, template_folder="static/templates", static_folder="static")


def free_port(port: int):
    """Kill any leftover dev server still bound to the requested port."""
    if os.name == "nt":
        return  # Windows uses a different toolchain; skip to avoid surprises.
    try:
        output = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"])  # macOS/Linux only
    except (subprocess.CalledProcessError, FileNotFoundError):
        return  # lsof not available or nothing is listening

    for pid_str in output.decode().strip().splitlines():
        if not pid_str:
            continue
        pid = int(pid_str)
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Killed leftover process %s holding port %s", pid, port)
        except ProcessLookupError:
            continue

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
  
def get_tasklist_title():
    """Return the title of the active Google Task list (best-effort)."""
    try:
        service = get_tasks_service()
        tl_id = ensure_tasklist_id(service)
        tl = service.tasklists().get(tasklist=tl_id).execute()
        return tl.get("title", TASKLIST_TITLE or "Tasks")
    except Exception:
        return TASKLIST_TITLE or "Tasks"


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


@app.route("/")
def home():
    # Render dashboard.html with the active task list name
    return render_template(
        "dashboard.html",
        active_list_title=get_tasklist_title(),
        ingest_token=INGEST_TOKEN,
    )

@app.route("/mobile")
def mobile():
    # Render mobile.html with the same variable
    return render_template(
        "mobile.html",
        active_list_title=get_tasklist_title(),
        ingest_token=INGEST_TOKEN,
    )

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
    # Only reclaim the port on the initial run; the reloader child shouldn't kill itself.
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        free_port(PORT)
        logger.info("Ensuring Google OAuth token is available before starting server...")
        try:
            get_creds()
        except Exception:
            logger.exception("OAuth flow failed. Fix the issue above and restart the server.")
            raise
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=True,
        ssl_context=("Giuseppes-MacBook-Air.local+1.pem", "Giuseppes-MacBook-Air.local+1-key.pem"),
    )
