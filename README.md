# Net Profile Manager

> **Disclaimer**
>
> Net Profile Manager is an independent, unofficial project. It is not affiliated with, endorsed by, or sponsored by TP-Link or Omada.
>
> TP-Link and Omada are trademarks of their respective owners. They are referenced only to describe compatibility with the Omada Open API.
>
> Use this software only on networks you own or are authorized to manage.

---

Net Profile Manager can be used as a lightweight parental control and device access dashboard
for TP-Link Omada networks.

A self-hosted web app that adds a simple household profile layer on top of a
local TP-Link Omada Controller using the Omada Open API.

Confirmed working against **Omada Software Controller 6.2**.

---

## What the App Does

Omada can show clients and block them individually, but it has no built-in
concept of "household profiles" — groups of devices that belong to a person
(a child, a tablet group, a guest) that you can pause or resume with one tap.

This app fills that gap:

- Connect to your local Omada Controller via the Open API
- See all Omada clients (devices) with their name, IP, MAC, online/blocked status
- Create local profiles (Kids, Tablets, Guest, etc.)
- Assign Omada clients to profiles by MAC address
- Pause or resume one device at a time
- Pause or resume every device in a profile with one button
- **Pause timers** — quick 15 min / 30 min / 1 hr / 2 hr buttons, or pick a specific "until" time; devices resume automatically when the timer fires
- **Recurring schedules** — per-profile pause and resume times on selected days of the week; survives restarts; manual overrides still work
- Keep all profile and device data in a local SQLite database
- View a simple action history log
- Access everything from a phone or desktop browser — no app to install

---

## What It Does Not Do

- DPI application blocking
- VLAN or SSID management
- Expose anything publicly (LAN only by default)
- Replace the Omada Controller

---

## Requirements

- Docker and Docker Compose on your homelab host
- A running TP-Link Omada Software Controller (tested on 6.2)
- Omada Open API credentials — **Client** mode (see below)
- Your Omada Controller admin username and password (for block/unblock)

---

## Creating Omada API Credentials

You register an API application inside the Omada Controller web UI.

### Steps

1. Log in to the **Omada Controller web UI**
2. Switch to **Global View** (top-left dropdown)
3. Go to **Settings → Platform Integration → Open API**
4. Click **Add New App**
5. Select **Client** mode — **not** Authorization Code
6. Copy the generated values:
   - **Client ID** → `OMADA_CLIENT_ID`
   - **Client Secret** → `OMADA_CLIENT_SECRET`
7. Copy your **Omada ID** (also called omadacId) — shown on the same Open API page
   or visible in the browser URL bar when logged into the controller → `OMADA_CONTROLLER_ID`
8. Find your **Site ID**:
   - Go to **Settings → Test Connection** in this app after setup, then look at the
     discovered sites table — it shows site names and their IDs
   - Put the correct ID into `OMADA_SITE_ID`

> **Important:** Use **Client** mode, not Authorization Code. Auth Code requires a
> browser redirect and will not work with this app.

---

## How the API Connection Works (Omada 6.2)

For reference, in case you need to troubleshoot or adapt this to another firmware version:

**Token authentication:**
```
POST {base_url}/openapi/authorize/token?grant_type=client_credentials
Content-Type: application/json

{
  "omadacId": "<your controller ID>",
  "client_id": "<your client ID>",
  "client_secret": "<your client secret>"
}
```

**Client listing:**
```
POST {base_url}/openapi/v2/{omadacId}/sites/{siteId}/clients
Authorization: AccessToken=<token>

{"page": 1, "pageSize": 200}
```

**Block / Unblock** — the Omada Open API does not expose block/unblock endpoints.
This app uses the private controller UI API with a session login:
```
POST {base_url}/api/v2/login              — authenticate with admin credentials
GET  {base_url}/api/v2/current/login-status?needToken=true  — get CSRF token
POST {base_url}/{omadacId}/api/v2/sites/{siteId}/cmd/clients/{MAC}/block
POST {base_url}/{omadacId}/api/v2/sites/{siteId}/cmd/clients/{MAC}/unblock
```
MAC addresses must use dashes: `AA-BB-CC-DD-EE-FF`. The app converts automatically.

---

## Quick Start — Guided Setup (recommended)

```bash
git clone https://github.com/walrus-walker/net-profile-manager.git
cd net-profile-manager
./scripts/setup.sh

The script will:

1. Check Docker and Docker Compose prerequisites
2. Walk through entering your Omada API credentials
3. Ask for your Omada admin username and password (for block/unblock)
4. Set an Admin PIN for the web UI
5. Auto-generate a cryptographic secret key
6. Write `.env` and start the container
7. Print the URL to open in your browser

Run it again any time to update the configuration.

---

## Manual Setup

```bash
cp .env.example .env
nano .env
# Fill in all values, then:
docker compose up -d
docker compose logs -f
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OMADA_BASE_URL` | Yes | Controller URL, e.g. `https://192.168.1.10:8043` — no trailing slash |
| `OMADA_CONTROLLER_ID` | Yes | The omadacId shown on the Open API page |
| `OMADA_CLIENT_ID` | Yes | Client ID from your Client-mode Open API app |
| `OMADA_CLIENT_SECRET` | Yes | Client Secret from your Client-mode Open API app |
| `OMADA_SITE_ID` | Yes | Site ID from Settings → Test Connection → discovered sites |
| `OMADA_VERIFY_SSL` | No | `false` to skip TLS cert check (use with self-signed certs) |
| `OMADA_UI_USERNAME` | Yes* | Omada controller admin username — required for block/unblock |
| `OMADA_UI_PASSWORD` | Yes* | Omada controller admin password — required for block/unblock |
| `APP_HOST` | No | Bind address inside container (default: `0.0.0.0`) |
| `APP_PORT` | No | Port the app listens on (default: `8095`) |
| `APP_ADMIN_PIN` | Yes | PIN to unlock the web UI |
| `APP_SECRET_KEY` | Yes | Secret for session cookies — use `openssl rand -hex 32` |
| `DATABASE_PATH` | No | SQLite path inside container (default: `/data/net-profile-manager.db`) |
| `DISCORD_WEBHOOK_URL` | No | Optional webhook, not yet used |

*Block/unblock works only when `OMADA_UI_USERNAME` and `OMADA_UI_PASSWORD` are set.

### Timezone

Timezone is configured inside the app, not via `.env`. After setup, open
**Settings → Timezone** and pick your region from the dropdown. The default
is `America/Chicago` until changed.

---

## First Login

1. Open the app: `http://your-host-ip:8095`
2. Enter the PIN you set in `APP_ADMIN_PIN`

From your phone: connect to your home network (or VPN/Tailscale/ZeroTier) and open the same URL.

---

## Basic Workflow

**Test the connection** → Settings → **Test Connection**

**List devices** → Devices → **Refresh from Omada**

**Create a profile** → Profiles → enter a name → **Create Profile**

**Assign a device** → Devices → find the device → select a profile → **Add**

**Pause or resume a profile** → Profiles → **⏸ Pause All** or **▶ Resume All**

**Pause with a timer** → Profiles or Devices → tap **15m / 30m / 1h / 2h** or enter an "Until" time → devices resume automatically

**Set a recurring schedule** → Profile detail page → **Recurring Schedule** section → pick days, pause time, resume time, save

---

## Security Notes

- **LAN only** — do not expose this app directly to the internet
- Use Tailscale, ZeroTier, or WireGuard for remote access
- Never commit `.env` or any file with real credentials
- See [SECURITY.md](SECURITY.md) for full guidance

---

## Troubleshooting

**"Cannot reach Omada controller"**
- Check `OMADA_BASE_URL` — include the port, no trailing slash
- Set `OMADA_VERIFY_SSL=false` if using a self-signed certificate

**Token auth fails (-1001)**
- Make sure your Open API app is **Client** mode, not Authorization Code
- Verify `OMADA_CLIENT_ID` and `OMADA_CLIENT_SECRET` match the Client-mode app exactly
- Verify `OMADA_CONTROLLER_ID` is the omadacId from the Open API page

**Block/Unblock fails**
- Set `OMADA_UI_USERNAME` and `OMADA_UI_PASSWORD` to your Omada web UI admin credentials
- Restart the container after updating `.env`: `docker restart net-profile-manager`

**No clients after refresh**
- Go to Devices → **Refresh from Omada**
- Check Settings → **Test Connection** first
- Verify `OMADA_SITE_ID` matches a site shown in the test connection results

**Container won't start**
- Run `docker compose logs` for missing variable errors
- Re-run `./scripts/setup.sh` to fix the configuration interactively

---

## Project Structure

```
net-profile-manager/
├── scripts/
│   ├── setup.sh          — Guided setup and deployment wizard (start here)
│   └── apply-env.sh      — Simple env copy helper
├── app/
│   ├── main.py           — FastAPI app, auth routes, startup
│   ├── config.py         — Pydantic settings from environment
│   ├── omada_client.py   — All Omada API calls isolated here
│   ├── database.py       — SQLite setup and queries
│   ├── auth.py           — PIN verification, session helpers
│   ├── worker.py         — Background scheduler (timers + recurring schedules)
│   ├── routes/
│   │   ├── devices.py    — Device list, pause/resume, assign
│   │   ├── profiles.py   — Profile CRUD, bulk pause/resume
│   │   └── schedules.py  — Timer and recurring schedule endpoints
│   ├── templates/        — Jinja2 HTML templates
│   └── static/style.css  — All styles, responsive, no framework
├── data/                 — SQLite database (Docker volume mount)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── SECURITY.md
```

---

## Future Roadmap

- Filter and search the device list
- Discord webhook notifications for pause/resume actions
- Export profiles and device assignments as JSON
- Dark mode UI option
