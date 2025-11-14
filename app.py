import os
from datetime import datetime, timezone

from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    session,
    redirect,
    url_for,
    abort,
)
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from authlib.integrations.flask_client import OAuth

import time
import re
import requests
import signal
import subprocess

from PIL import Image
import pkgutil

if not hasattr(pkgutil, "find_loader"):
    from importlib.machinery import PathFinder

    def _compat_find_loader(fullname):
        spec = PathFinder.find_spec(fullname)
        return spec.loader if spec else None

    pkgutil.find_loader = _compat_find_loader  # type: ignore[attr-defined]
import numpy as np
import easyocr

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/tasks"]
PORT = int(os.getenv("PORT", "5000"))
TASKLIST_TITLE = os.getenv("TASKLIST_TITLE", "").strip()
FLASK_SECRET = os.getenv("FLASK_SECRET", "").strip()
if not FLASK_SECRET:
    raise RuntimeError("FLASK_SECRET must be set for session handling.")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required.")
GOOGLE_AUTH_REDIRECT_URI = os.getenv("GOOGLE_AUTH_REDIRECT_URI", "").strip()
GOOGLE_SCOPES = ["openid", "email", "profile"] + SCOPES
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_API_BASE = "https://accounts.google.com/.well-known/openid-configuration"
CERT_PATH = os.getenv("CERT_PATH", "local.pem").strip()
CERT_KEY_PATH = os.getenv("CERT_KEY_PATH", "local-key.pem").strip()
EASYOCR_LANGS = [lang.strip() for lang in os.getenv("EASYOCR_LANGS", "en").split(",") if lang.strip()]
if not EASYOCR_LANGS:
    EASYOCR_LANGS = ["en"]
EASYOCR_USE_GPU = os.getenv("EASYOCR_USE_GPU", "0").lower() in {"1", "true", "yes"}

# Tell Flask where the Jinja templates actually live (they're under static/templates).
app = Flask(__name__, template_folder="static/templates", static_folder="static")
app.secret_key = FLASK_SECRET

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url=GOOGLE_API_BASE,
    client_kwargs={
        "scope": " ".join(GOOGLE_SCOPES),
        "prompt": "consent",
        "access_type": "offline",
    },
)

PUBLIC_ENDPOINTS = {"login", "auth_callback", "logout", "static", "version"}


def _init_easyocr():
    try:
        logger.info("Initializing EasyOCR reader (langs=%s, gpu=%s)", EASYOCR_LANGS, EASYOCR_USE_GPU)
        return easyocr.Reader(EASYOCR_LANGS, gpu=EASYOCR_USE_GPU, verbose=False)
    except Exception:
        logger.exception("Failed to initialize EasyOCR")
        return None


OCR_ENGINE = _init_easyocr()


def is_logged_in() -> bool:
    return "google_token" in session


@app.before_request
def enforce_login():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return
    if not is_logged_in():
        return redirect(url_for("login"))


def _redirect_uri():
    if GOOGLE_AUTH_REDIRECT_URI:
        return GOOGLE_AUTH_REDIRECT_URI
    return url_for("auth_callback", _external=True)


@app.route("/login")
def login():
    return oauth.google.authorize_redirect(_redirect_uri())


@app.route("/auth/callback")
def auth_callback():
    token = oauth.google.authorize_access_token()
    session["google_token"] = token
    userinfo = token.get("userinfo")
    if not userinfo:
        resp = oauth.google.get("userinfo")
        resp.raise_for_status()
        userinfo = resp.json()
    session["user_email"] = userinfo.get("email")
    session.pop("tasklist_id", None)
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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
def get_tasks_service():
    creds = get_user_credentials()
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
    tasklist_id = session.get("tasklist_id")
    if tasklist_id:
        return tasklist_id
    lists = service.tasklists().list(maxResults=10).execute()
    if "items" in lists and lists["items"]:
        tasklist_id = lists["items"][0]["id"]
        session["tasklist_id"] = tasklist_id
        return tasklist_id
    created = service.tasklists().insert(body={"title": TASKLIST_TITLE or "Tasks"}).execute()
    tasklist_id = created["id"]
    session["tasklist_id"] = tasklist_id
    return tasklist_id


def _build_credentials_from_token(token: dict) -> Credentials:
    expiry_ts = token.get("expires_at")
    expiry = None
    if expiry_ts:
        try:
            expiry = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
        except Exception:
            expiry = None
    if expiry is not None:
        # google-auth expects naive UTC timestamps for comparisons
        expiry = expiry.replace(tzinfo=None)
    return Credentials(
        token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        token_uri=GOOGLE_TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
        expiry=expiry,
        id_token=token.get("id_token"),
    )


def get_user_credentials() -> Credentials:
    token = session.get("google_token")
    if not token:
        abort(401)
    creds = _build_credentials_from_token(token)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            updated = dict(token)
            updated["access_token"] = creds.token
            if creds.expiry:
                updated["expires_at"] = int(creds.expiry.timestamp())
            session["google_token"] = updated
        except Exception:
            session.pop("google_token", None)
            session.pop("user_email", None)
            logger.exception("Failed to refresh Google token; forcing re-login.")
            abort(401)
    return creds


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


# ---------- Routes ----------


@app.route("/")
def home():
    # Render dashboard.html with the active task list name
    return render_template(
        "dashboard.html",
        active_list_title=get_tasklist_title(),
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
                "selected": session.get("tasklist_id"),
            }
        )
    except Exception as exc:
        logger.exception("Failed to list tasklists")
        return jsonify(
            {"items": [], "selected": session.get("tasklist_id"), "error": str(exc)}
        ), 500


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
    session["tasklist_id"] = tasklist_id
    title = tl.get("title", TASKLIST_TITLE or "Tasks")
    logger.info("Tasklist selected: %s (%s)", title, tasklist_id)
    return jsonify({"ok": True, "title": title, "tasklist_id": tasklist_id})

@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}

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


def extract_text_with_easyocr(image: Image.Image) -> str:
    if OCR_ENGINE is None:
        raise RuntimeError("EasyOCR reader unavailable")
    np_img = np.array(image.convert("RGB"))
    try:
        results = OCR_ENGINE.readtext(np_img, detail=0)
    except Exception as exc:
        raise RuntimeError(f"EasyOCR inference failed: {exc}") from exc
    lines = []
    for entry in results or []:
        text = (entry or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


@app.route("/ocr", methods=["POST"])
def ocr():
    """Accept an uploaded image and return OCR text."""
    if "image" not in request.files:
        return jsonify({"ok": False, "message": "Missing image upload"}), 400

    file = request.files["image"]
    if not file or file.filename == "":
        return jsonify({"ok": False, "message": "Invalid file"}), 400

    try:
        raw_image = Image.open(file.stream).convert("RGB")
    except Exception:
        logger.exception("Unable to open uploaded file for OCR")
        return jsonify({"ok": False, "message": "Unable to read image"}), 400

    try:
        text = extract_text_with_easyocr(raw_image)
    except Exception as exc:
        logger.exception("EasyOCR failed")
        return jsonify({"ok": False, "message": f"OCR failed: {exc}"}), 500
    return jsonify({"ok": True, "text": text, "engine": "easyocr", "languages": EASYOCR_LANGS})

# expose version everywhere in templates
@app.context_processor
def inject_version():
    ver = os.getenv("IMAGE_TAG", "unknown")
    return {
        "version": ver,
        "app_version": ver,
        "user_email": session.get("user_email"),
        "logged_in": is_logged_in(),
    }

@app.route("/version")
def version():
    import os
    tag = os.getenv("IMAGE_TAG", "unknown")
    return jsonify({"version": tag})

if __name__ == "__main__":
    # Only reclaim the port on the initial run; the reloader child shouldn't kill itself.
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        free_port(PORT)
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=True,
        ssl_context=(CERT_PATH, CERT_KEY_PATH)
        if os.path.exists(CERT_PATH) and os.path.exists(CERT_KEY_PATH)
        else None,
    )
