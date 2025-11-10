## 🧭 TODO / Future Enhancements

- [ ] **Integrate QuaggaJS** to enable barcode scanning on iPhone (Safari lacks the `BarcodeDetector` API).
- [ ] **Optional Pi-hole cleanup/automation** scripts (enable/disable, backups, updates)
- [ ] **One section with selector**
- [ ] **Map domain & auth hardening**
  - [ ] Configure `gtemp1.com` (Hostinger) so requests proxy/redirect to the Docker endpoint.
  - [ ] Add basic authentication so only family members can access the dashboard/API.

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
