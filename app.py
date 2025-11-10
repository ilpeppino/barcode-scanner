import os
from datetime import datetime

from flask import Flask, request, jsonify, render_template, abort
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

import time
import re
import requests
import signal
import subprocess

from PIL import Image
import importlib
import pkgutil

if not hasattr(pkgutil, "find_loader"):
    from importlib.machinery import PathFinder

    def _compat_find_loader(fullname):
        spec = PathFinder.find_spec(fullname)
        return spec.loader if spec else None

    pkgutil.find_loader = _compat_find_loader  # type: ignore[attr-defined]
import pytesseract

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
        if creds:
            if creds.valid:
                return creds
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open("token.json", "w") as f:
                        f.write(creds.to_json())
                    logger.info("Refreshed stored Google OAuth token")
                    return creds
                except Exception:
                    logger.exception("Failed to refresh Google OAuth token; falling back to full flow")
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


def list_tasklists():
    service = get_tasks_service()
    result = service.tasklists().list(maxResults=100).execute() or {}
    items = result.get("items", [])
    # ensure we have a default selection cached
    ensure_tasklist_id(service)
    return items


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
    created = service.tasks().insert(tasklist=tl_id, body=body).execute()
    logger.info("Created task %s on list %s", created.get("id"), tl_id)
    return created


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


def log_scan(code, title=None):
    RECENT.insert(
        0,
        {
            "code": code,
            "title": title or "",
            "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    del RECENT[200:]  # keep last 200


def extract_ingest_token(preloaded_json=None) -> str:
    """Return the ingest token from JSON, form data, headers, or query params."""
    if preloaded_json and preloaded_json.get("token"):
        return preloaded_json.get("token")
    if request.form.get("token"):
        return request.form.get("token")
    header_token = request.headers.get("X-Ingest-Token")
    if header_token:
        return header_token
    if request.args.get("token"):
        return request.args.get("token")
    return None


# ---------- Routes ----------


@app.route("/")
def home():
    # Render dashboard.html with the active task list name
    return render_template(
        "dashboard.html",
        active_list_title=get_tasklist_title(),
        ingest_token=INGEST_TOKEN,
    )

@app.route("/recent")
def recent():
    return jsonify(RECENT)


@app.route("/tasklists")
def tasklists():
    try:
        items = list_tasklists()
        return jsonify(
            {
                "items": [{"id": i.get("id"), "title": i.get("title") or "Untitled"} for i in items],
                "selected": TASKLIST_ID,
            }
        )
    except Exception as exc:
        logger.exception("Failed to list tasklists")
        return jsonify({"items": [], "selected": TASKLIST_ID, "error": str(exc)}), 500


@app.route("/tasklists/select", methods=["POST"])
def select_tasklist():
    data = request.get_json(silent=True) or {}
    tasklist_id = (data.get("tasklist_id") or "").strip()
    if not tasklist_id:
        return jsonify({"ok": False, "message": "tasklist_id required"}), 400
    try:
        service = get_tasks_service()
        tl = service.tasklists().get(tasklist=tasklist_id).execute()
    except Exception as exc:
        logger.exception("Failed to fetch tasklist %s", tasklist_id)
        return jsonify({"ok": False, "message": "Unable to select task list"}), 400
    global TASKLIST_ID, TASKLIST_TITLE
    TASKLIST_ID = tasklist_id
    TASKLIST_TITLE = tl.get("title", TASKLIST_TITLE)
    logger.info("Tasklist selected: %s (%s)", TASKLIST_TITLE, TASKLIST_ID)
    return jsonify({"ok": True, "title": TASKLIST_TITLE, "tasklist_id": TASKLIST_ID})

@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}
    token = extract_ingest_token(data)
    if token != INGEST_TOKEN:
        logger.info(
            "Auth failed from %s: provided token len=%s (expected non-empty). Hint: set INGEST_TOKEN in .env and enter the same value on the dashboard.",
            request.remote_addr,
            len(token) if token else 0,
        )
        abort(401)

    raw = (data.get("code") or "").strip()
    logger.info("Received scan request from %s: %s", request.remote_addr, raw)
    if not raw:
        return jsonify({"ok": False, "message": "Missing code"}), 400

    code = normalize_barcode(raw)
    if is_recent_duplicate(code):
        logger.info("Duplicate detected for code %s - ignoring", code)
        log_scan(code + " (dup ignored)", title="Duplicate ignored")
        return jsonify({"ok": True, "message": f"Ignored duplicate: {code}"}), 200

    title, notes = lookup_product_title_notes(code)
    logger.info("Creating task for code %s with title '%s'", code, title)
    try:
        create_task(title=title, notes=notes)
    except Exception as exc:
        logger.exception("Failed to create task for code %s", code)
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Failed to create Google Task. Check server logs and re-authenticate if needed.",
                }
            ),
            500,
        )
    logger.info("Task created successfully for %s", code)
    log_scan(code, title=title)
    return jsonify({"ok": True, "message": f"Added task: {title}"}), 200


@app.route("/recent/clear", methods=["POST"])
def clear_recent():
    RECENT.clear()
    LAST_SEEN.clear()
    return jsonify({"ok": True})


@app.route("/ocr", methods=["POST"])
def ocr():
    """Accept an uploaded image and return OCR text."""
    token = extract_ingest_token()
    if token != INGEST_TOKEN:
        abort(401)

    if "image" not in request.files:
        return jsonify({"ok": False, "message": "Missing image upload"}), 400

    file = request.files["image"]
    if not file or file.filename == "":
        return jsonify({"ok": False, "message": "Invalid file"}), 400

    try:
        image = Image.open(file.stream).convert("RGB")
    except Exception:
        logger.exception("Unable to open uploaded file for OCR")
        return jsonify({"ok": False, "message": "Unable to read image"}), 400

    language = request.form.get("language") or "eng"
    config = request.form.get("tesseract_config") or ""
    try:
        text = pytesseract.image_to_string(image, lang=language, config=config).strip()
    except pytesseract.TesseractError as exc:
        logger.exception("Tesseract OCR failed")
        return jsonify({"ok": False, "message": f"OCR failed: {exc}"}), 500
    return jsonify({"ok": True, "text": text, "language": language})

# expose version everywhere in templates
@app.context_processor
def inject_version():
    return {"version": os.getenv("IMAGE_TAG", "unknown")}

@app.route("/version")
def version():
    import os
    tag = os.getenv("IMAGE_TAG", "unknown")
    return jsonify({"version": tag})

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
        ssl_context=("local.pem", "local-key.pem"),
    )
