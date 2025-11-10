## 🧭 TODO / Future Enhancements

- [ ] **Integrate QuaggaJS** to enable barcode scanning on iPhone (Safari lacks the `BarcodeDetector` API).
- [ ] **Implement OCR** (Optical Character Recognition) to read printed text alongside barcodes.
- [ ] **Explore lightweight NAS-side OCR integration** (e.g., Tesseract in a sidecar container) and expose a `/ocr` endpoint.
- [x] **Add build version to the web app footer** using a Flask `app_version` context processor (reads `IMAGE_TAG`).
- [x] **Document Android CA installation and HTTPS trust config** for new devices (mkcert CA → camera works).
- [ ] **Optional Pi-hole cleanup/automation** scripts (enable/disable, backups, updates)
- [ ] **Camera portrait mode**
- [ ] **One section with selector**

### New

- [ ] **OAuth login with Google (multi-user)**
  - [ ] Add “Sign in with Google” (OAuth 2.0, Authorization Code Flow with PKCE).
  - [ ] Store per-user Google tokens securely (refresh tokens, token rotation).
  - [ ] Scope: `https://www.googleapis.com/auth/tasks` (Google Tasks read/write).
  - [ ] Map each signed-in user to their own Tasks list selection (persist preference).
  - [ ] Protect all write APIs with session auth (Flask session / server-side store).
  - [ ] Configure redirect URIs for **local** (https://localhost:5000/auth/callback), **NAS LAN** (https://192.168.178.45:5050/auth/callback), and **public** (https://scanner.gtemp1.com/auth/callback).
  - [ ] Use Docker secrets / env vars for `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FLASK_SECRET_KEY`.
  - [ ] Add logout, CSRF protection, and role flags (admin vs. standard user).
