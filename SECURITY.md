# Security Notes — Net Profile Manager

## Intended Use

This application is designed for **private LAN use only**.

It is a homelab prototype. It is not hardened for public exposure.

---

## Network Access

**Do not expose this app directly to the internet.**

Recommended access methods (choose one):

- **LAN only** — run it on your home network and access it from trusted devices
- **ZeroTier** — access it remotely through your ZeroTier network
- **WireGuard VPN** — connect to your home network via WireGuard, then access normally
- **Tailscale** — similar to ZeroTier, easy to set up

If you use a reverse proxy (Nginx, Caddy, Traefik), keep it behind authentication
and restricted to your internal network or VPN.

---

## Secrets and Credentials

- **Never commit your `.env` file** — it contains real credentials.
- **Never commit `.env.desktop`** or any `.env.*` files other than `.env.example`.
- **Never commit database files** — they may contain device names and action history.
- **Never commit screenshots** showing real IP addresses, device names, or MAC addresses.
- **Never commit logs** that may contain API responses or client data.

The `.gitignore` in this project already excludes these files. Do not override it.

---

## Admin PIN

- Set `APP_ADMIN_PIN` to a strong, unique PIN — not a short numeric PIN.
- The PIN is hashed with SHA-256 before comparison. It is never stored in plaintext.
- The PIN is never displayed in the UI or logged.

---

## Omada API Credentials

- `OMADA_CLIENT_ID` and `OMADA_CLIENT_SECRET` are stored only in your `.env` file.
- They are never displayed in the settings UI.
- They are never logged by the application.
- If compromised, revoke and regenerate them in the Omada Controller web UI under
  **Global View → Settings → Platform Integration → Open API**.

---

## TLS / SSL

- If your Omada Controller uses a self-signed certificate (common in homelabs),
  set `OMADA_VERIFY_SSL=false`.
- For production-quality homelab setups, issue a proper certificate (e.g., via
  Let's Encrypt with a local DNS challenge) and set `OMADA_VERIFY_SSL=true`.

---

## App Session Security

- Sessions are signed with `APP_SECRET_KEY`. Use a long random string.
  Generate one with: `openssl rand -hex 32`
- If you rotate `APP_SECRET_KEY`, all active sessions will be invalidated.

---

## Data Stored Locally

The SQLite database stores:

- Profile names and descriptions
- Device MAC addresses and display names you assign
- Action history (block/unblock attempts and results)
- Cached Omada client data (name, IP, online/blocked status)

It does **not** store Omada API credentials or session tokens.

---

## Reporting Issues

This is a private homelab prototype. If you find a security issue, review the
relevant code in `app/omada_client.py`, `app/auth.py`, and `app/database.py`
and fix it directly.
