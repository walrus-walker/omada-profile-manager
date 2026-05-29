#!/usr/bin/env bash
# =============================================================================
# setup.sh — Net Profile Manager  |  Guided Setup & Launch
# =============================================================================
# This script walks you through the full setup and starts the app.
# Run it once to set up, or again any time to update your configuration.
#
# Requirements: Docker with Docker Compose plugin (or docker-compose v1)
#
# Usage:
#   cd coding-projects/python/net-profile-manager
#   ./scripts/setup.sh
# =============================================================================

# Guard: must be run with bash, not sh/dash
if [ -z "${BASH_VERSION:-}" ]; then
  echo "ERROR: This script requires bash. Run it with:  bash ./scripts/setup.sh"
  exit 1
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

# =============================================================================
# Colour setup
# Use $'...' so escape codes are embedded in the variable itself.
# printf then works without any flags — no echo -e needed anywhere.
# =============================================================================
if [ -t 1 ]; then
  RED=$'\033[0;31m'
  GREEN=$'\033[0;32m'
  YELLOW=$'\033[1;33m'
  BLUE=$'\033[0;34m'
  CYAN=$'\033[0;36m'
  BOLD=$'\033[1m'
  DIM=$'\033[2m'
  NC=$'\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; BOLD=''; DIM=''; NC=''
fi

# =============================================================================
# Output helpers — all use printf, never echo -e
# =============================================================================
banner()  { printf "\n%s%s━━  %s  ━━%s\n"  "$BOLD" "$CYAN"   "$*" "$NC"; }
ok()      { printf "  %s✓%s  %s\n"          "$GREEN"          "$NC" "$*"; }
warn()    { printf "  %s⚠%s   %s\n"         "$YELLOW"         "$NC" "$*"; }
err()     { printf "  %s✗%s  %s\n"          "$RED"            "$NC" "$*"; }
info()    { printf "  %sℹ%s   %s\n"         "$BLUE"           "$NC" "$*"; }
heading() { printf "\n%s  %s%s\n"           "$BOLD"           "$*" "$NC"; }
dim()     { printf "%s  %s%s\n"             "$DIM"            "$*" "$NC"; }
blank()   { printf "\n"; }

# =============================================================================
# Input helpers
# =============================================================================

# ask <label> [default]  →  result in $REPLY
ask() {
  local label="$1" default="${2:-}"
  if [[ -n "$default" ]]; then
    printf "  %s [%s%s%s]: " "$label" "$BOLD" "$default" "$NC"
  else
    printf "  %s: " "$label"
  fi
  read -r REPLY || true
  if [[ -z "$REPLY" && -n "$default" ]]; then REPLY="$default"; fi
}

# ask_secret <label>  →  result in $REPLY  (input hidden)
ask_secret() {
  printf "  %s: " "$1"
  read -rs REPLY || true
  printf "\n"
}

# ask_yn <label> [default y|n]  →  returns 0 for yes, 1 for no
ask_yn() {
  local label="$1" default="${2:-y}" hint
  [[ "$default" == "y" ]] && hint="Y/n" || hint="y/N"
  printf "  %s [%s]: " "$label" "$hint"
  read -r REPLY || true
  if [[ -z "$REPLY" ]]; then REPLY="$default"; fi
  [[ "${REPLY,,}" =~ ^y ]]
}

# =============================================================================
# Docker PATH augmentation
# Docker Desktop on macOS/Linux installs to paths not always in $PATH.
# Add the common locations before any docker checks run.
# =============================================================================
_augment_docker_path() {
  local candidates=(
    "/usr/local/bin"
    "/usr/bin"
    "/opt/homebrew/bin"
    "$HOME/.docker/bin"
    "/Applications/Docker.app/Contents/Resources/bin"
    "/Applications/Docker.app/Contents/MacOS"
  )
  for _d in "${candidates[@]}"; do
    if [[ -d "$_d" && ":$PATH:" != *":$_d:"* ]]; then
      export PATH="$PATH:$_d"
    fi
  done
}

# Portable LAN IP detection (Linux + macOS)
_local_ip() {
  # Linux: hostname -I prints all IPs space-separated
  local ip
  ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  [[ -n "$ip" ]] && { printf "%s" "$ip"; return; }
  # macOS: try common interface names
  for iface in en0 en1 eth0; do
    ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
    [[ -n "$ip" ]] && { printf "%s" "$ip"; return; }
  done
  printf "your-host-ip"
}

# =============================================================================
# STEP 1 — Prerequisites
# =============================================================================
check_prerequisites() {
  banner "Checking Requirements"
  blank

  _augment_docker_path

  # ---- Docker CLI ------------------------------------------------------------
  if ! command -v docker &>/dev/null; then
    err "Docker command not found."
    blank
    info "Install Docker Desktop from:"
    info "  https://docs.docker.com/get-docker/"
    blank
    info "If Docker IS installed, it may not be in your PATH."
    info "Try opening a new terminal after installing, or run:"
    info "  export PATH=\"\$PATH:/usr/local/bin\"  (Linux)"
    info "  export PATH=\"\$PATH:\$HOME/.docker/bin\"  (newer Docker Desktop)"
    exit 1
  fi
  ok "Docker found: $(docker --version)"

  # ---- Docker daemon ---------------------------------------------------------
  if ! docker info &>/dev/null 2>&1; then
    err "Docker daemon is not running (or this user lacks permission)."
    blank
    info "macOS / Windows : open the Docker Desktop application"
    info "Linux (systemd) : sudo systemctl start docker"
    info "Linux (permission fix) :"
    info "  sudo usermod -aG docker \$USER"
    info "  Then log out and back in, and try again."
    exit 1
  fi
  ok "Docker daemon is running"

  # ---- Docker Compose --------------------------------------------------------
  if docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    ok "Docker Compose v2 found: $(docker compose version)"
  elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
    ok "docker-compose v1 found: $(docker-compose --version)"
  else
    err "Docker Compose is not installed."
    blank
    info "Install the Docker Compose plugin:"
    info "  https://docs.docker.com/compose/install/"
    exit 1
  fi

  # ---- Project directory -----------------------------------------------------
  if [[ ! -f "$PROJECT_DIR/docker-compose.yml" ]]; then
    err "docker-compose.yml not found at: $PROJECT_DIR"
    info "Run this script from within the net-profile-manager directory."
    exit 1
  fi
  ok "Project directory confirmed"
}

# =============================================================================
# Site ID discovery — runs inline Python using credentials just entered
# Outputs "name|siteId" lines on success, nothing on failure.
# =============================================================================
_discover_sites() {
  local _base="$1" _id="$2" _cid="$3" _secret="$4" _ssl="$5"

  python3 - "$_base" "$_id" "$_cid" "$_secret" "$_ssl" 2>/dev/null <<'PYEOF'
import sys, json, ssl
from urllib import request, error

base_url, omadac_id, client_id, client_secret, verify_ssl_str = sys.argv[1:]
verify_ssl = verify_ssl_str.lower() in ("1", "true", "yes", "on")

if not base_url.startswith(("http://", "https://")):
    base_url = "https://" + base_url
base_url = base_url.rstrip("/")

ctx = None
if base_url.startswith("https://") and not verify_ssl:
    ctx = ssl._create_unverified_context()

def http_json(method, url, body=None, headers=None):
    headers = headers or {}
    data = None
    if body:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, context=ctx, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        sys.exit(1)

resp = http_json("POST",
    f"{base_url}/openapi/authorize/token?grant_type=client_credentials",
    {"omadacId": omadac_id, "client_id": client_id, "client_secret": client_secret})

if resp.get("errorCode") not in (0, "0", None):
    sys.exit(1)

token = resp.get("result", {}).get("accessToken") or resp.get("accessToken", "")
if not token:
    sys.exit(1)

resp2 = http_json("GET",
    f"{base_url}/openapi/v1/{omadac_id}/sites?page=1&pageSize=100",
    headers={"Authorization": f"AccessToken={token}"})

if resp2.get("errorCode") not in (0, "0", None):
    sys.exit(1)

result = resp2.get("result", {})
sites = (
    result.get("data") if isinstance(result, dict) else
    result if isinstance(result, list) else
    resp2.get("data", [])
)

for s in sites:
    name = s.get("name") or s.get("siteName") or "(unnamed)"
    sid  = s.get("siteId") or s.get("id") or ""
    if sid:
        print(f"{name}|{sid}")
PYEOF
}

# =============================================================================
# STEP 2 — Configuration wizard
# =============================================================================
configure() {
  banner "Configuration"

  if [[ -f "$ENV_FILE" ]]; then
    blank
    warn "An existing .env file was found."
    if ask_yn "Use the existing configuration (skip re-entering values)?" "y"; then
      ok "Using existing .env — skipping setup wizard."
      return 0
    fi
    blank
    info "OK — let's set up a new configuration from scratch."
  fi

  blank
  printf "  %sWhere to find Omada API values:%s\n" "$BOLD" "$NC"
  printf "  %s  Omada web UI → Global View → Settings → Platform Integration → Open API%s\n" "$BLUE" "$NC"
  blank
  printf "  %s(Press Enter to accept a default shown in [brackets])%s\n" "$DIM" "$NC"
  blank

  # ---- Omada Controller URL --------------------------------------------------
  heading "Omada Controller URL"
  dim "The local address of your Omada Controller, including the port number."
  dim "Example:  https://192.168.1.10:8043  (Omada's default port is 8043)"
  blank
  while true; do
    ask "Controller URL"
    [[ -n "$REPLY" ]] && break
    err "This field is required."
  done
  OMADA_BASE_URL="${REPLY%/}"

  # ---- Omada Controller ID ---------------------------------------------------
  blank
  heading "Omada Controller ID  (also called Omada ID)"
  dim "Shown on the Open API page in the Omada web UI."
  blank
  while true; do
    ask "Controller ID"
    [[ -n "$REPLY" ]] && break
    err "This field is required."
  done
  OMADA_CONTROLLER_ID="$REPLY"

  # ---- Omada Client ID -------------------------------------------------------
  blank
  heading "Omada Client ID"
  dim "Generated by Omada when you created an Open API application."
  blank
  while true; do
    ask "Client ID"
    [[ -n "$REPLY" ]] && break
    err "This field is required."
  done
  OMADA_CLIENT_ID="$REPLY"

  # ---- Omada Client Secret ---------------------------------------------------
  blank
  heading "Omada Client Secret"
  dim "Generated by Omada alongside the Client ID.  (input will be hidden)"
  blank
  while true; do
    ask_secret "Client Secret"
    [[ -n "$REPLY" ]] && break
    err "This field is required."
  done
  OMADA_CLIENT_SECRET="$REPLY"

  # ---- Omada UI credentials --------------------------------------------------
  blank
  heading "Omada Admin Username & Password"
  dim "Your Omada Controller web UI login — required for Pause/Resume (block/unblock)."
  dim "These are the credentials you use to log in to the Omada web dashboard."
  blank
  while true; do
    ask "Omada admin username"
    [[ -n "$REPLY" ]] && break
    err "This field is required."
  done
  OMADA_UI_USERNAME="$REPLY"

  blank
  while true; do
    ask_secret "Omada admin password"
    [[ -n "$REPLY" ]] && break
    err "This field is required."
  done
  OMADA_UI_PASSWORD="$REPLY"
  ok "Omada admin credentials saved"

  # ---- SSL -------------------------------------------------------------------
  blank
  heading "SSL Certificate Verification"
  dim "Most home Omada controllers use a self-signed certificate."
  dim "Answering 'no' (recommended for home use) skips certificate verification."
  blank
  if ask_yn "Verify the Omada controller SSL certificate?" "n"; then
    OMADA_VERIFY_SSL="true"
    ok "SSL verification: enabled"
  else
    OMADA_VERIFY_SSL="false"
    ok "SSL verification: disabled (self-signed cert mode)"
  fi

  # ---- Omada Site ID — auto-discovery ----------------------------------------
  blank
  heading "Omada Site ID"
  blank
  OMADA_SITE_ID=""

  if command -v python3 &>/dev/null; then
    info "Contacting controller to discover sites (timeout: ~10s)..."
    blank

    DISC_OUTPUT="$(_discover_sites \
      "$OMADA_BASE_URL" "$OMADA_CONTROLLER_ID" \
      "$OMADA_CLIENT_ID" "$OMADA_CLIENT_SECRET" \
      "$OMADA_VERIFY_SSL")" || true

    if [[ -n "$DISC_OUTPUT" ]]; then
      # Parse name|id lines into arrays
      mapfile -t _SITE_LINES <<< "$DISC_OUTPUT"
      _SITE_COUNT="${#_SITE_LINES[@]}"

      ok "Found ${_SITE_COUNT} site(s):"
      blank

      for _i in "${!_SITE_LINES[@]}"; do
        IFS="|" read -r _sname _sid <<< "${_SITE_LINES[$_i]}"
        printf "  %s%d)%s  %-28s  %s%s%s\n" \
          "$BOLD" $((_i+1)) "$NC" \
          "$_sname" \
          "$DIM" "$_sid" "$NC"
      done
      blank

      if [[ "$_SITE_COUNT" -eq 1 ]]; then
        IFS="|" read -r _sname _sid <<< "${_SITE_LINES[0]}"
        if ask_yn "Use \"${_sname}\" (${_sid})?" "y"; then
          OMADA_SITE_ID="$_sid"
          ok "Site ID: $OMADA_SITE_ID"
        fi
      fi

      if [[ -z "$OMADA_SITE_ID" ]]; then
        while true; do
          printf "  %sEnter site number, or paste an ID directly:%s " "$BOLD" "$NC"
          read -r REPLY || true
          if [[ "$REPLY" =~ ^[0-9]+$ ]] && \
             [[ "$REPLY" -ge 1 && "$REPLY" -le "$_SITE_COUNT" ]]; then
            IFS="|" read -r _sname _sid <<< "${_SITE_LINES[$(( REPLY-1 ))]}"
            OMADA_SITE_ID="$_sid"
            ok "Selected: ${_sname}  (${OMADA_SITE_ID})"
            break
          elif [[ -n "$REPLY" ]]; then
            OMADA_SITE_ID="$REPLY"
            ok "Site ID: $OMADA_SITE_ID"
            break
          else
            err "Please enter a site number or paste an ID."
          fi
        done
      fi

    else
      warn "Could not reach the controller (wrong credentials, URL, or SSL setting?)."
      info "You can find your Site ID in the Omada web UI under Open API settings."
      blank
      ask "Site ID (or leave blank to set later)"
      OMADA_SITE_ID="$REPLY"
    fi

  else
    warn "python3 not found — skipping auto-discovery."
    dim  "Find your Site ID in the Omada web UI under Settings → Open API."
    blank
    ask "Site ID (or leave blank to set later)"
    OMADA_SITE_ID="$REPLY"
  fi

  if [[ -z "$OMADA_SITE_ID" ]]; then
    warn "Site ID left blank — add it to .env before using the Devices page."
  fi

  # ---- Port ------------------------------------------------------------------
  blank
  heading "Web App Port"
  dim "The port you will use to open the app in your browser."
  blank
  ask "Port number" "8095"
  APP_PORT="${REPLY//[^0-9]/}"
  if [[ -z "$APP_PORT" ]]; then APP_PORT="8095"; fi
  ok "Port: $APP_PORT"

  # ---- Admin PIN -------------------------------------------------------------
  blank
  heading "Admin PIN"
  dim "This PIN locks the web app.  Choose something you will remember."
  dim "(input will be hidden as you type)"
  blank
  while true; do
    ask_secret "Admin PIN"
    PIN1="$REPLY"
    [[ -z "$PIN1" ]] && { err "PIN cannot be empty."; continue; }
    ask_secret "Confirm PIN"
    PIN2="$REPLY"
    [[ "$PIN1" == "$PIN2" ]] && break
    err "PINs do not match — please try again."
    blank
  done
  APP_ADMIN_PIN="$PIN1"
  ok "Admin PIN set"

  # ---- Secret key (auto-generated) ------------------------------------------
  blank
  heading "Session Secret Key"
  dim "Used to secure login cookies.  Auto-generated for you — no input needed."
  blank
  if command -v openssl &>/dev/null; then
    APP_SECRET_KEY="$(openssl rand -hex 32)"
  else
    APP_SECRET_KEY="$(cat /dev/urandom | LC_ALL=C tr -dc 'a-zA-Z0-9' 2>/dev/null | dd bs=64 count=1 2>/dev/null || head -c 64 /dev/urandom | base64 | tr -d '+/=' | head -c 64)"
  fi
  ok "Secret key generated"

  DATABASE_PATH="/data/net-profile-manager.db"

  # ---- Write .env ------------------------------------------------------------
  blank
  banner "Saving Configuration"

  if [[ -f "$ENV_FILE" ]]; then
    BACKUP="${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$ENV_FILE" "$BACKUP"
    ok "Backed up existing .env to: $(basename "$BACKUP")"
  fi

  cat > "$ENV_FILE" <<ENVEOF
# Net Profile Manager — generated by setup.sh on $(date)
# Edit this file and re-run ./scripts/setup.sh to apply changes.
# WARNING: Do NOT commit this file to git.

OMADA_BASE_URL=${OMADA_BASE_URL}
OMADA_CONTROLLER_ID=${OMADA_CONTROLLER_ID}
OMADA_CLIENT_ID=${OMADA_CLIENT_ID}
OMADA_CLIENT_SECRET=${OMADA_CLIENT_SECRET}
OMADA_SITE_ID=${OMADA_SITE_ID}
OMADA_VERIFY_SSL=${OMADA_VERIFY_SSL}
OMADA_UI_USERNAME=${OMADA_UI_USERNAME}
OMADA_UI_PASSWORD=${OMADA_UI_PASSWORD}

APP_HOST=0.0.0.0
APP_PORT=${APP_PORT}
APP_ADMIN_PIN=${APP_ADMIN_PIN}
APP_SECRET_KEY=${APP_SECRET_KEY}
DATABASE_PATH=${DATABASE_PATH}

DISCORD_WEBHOOK_URL=
ENVEOF

  chmod 600 "$ENV_FILE"
  ok ".env written and locked (chmod 600)"
}

# =============================================================================
# STEP 3 — Build & Start
# =============================================================================
deploy() {
  banner "Building and Starting the App"
  blank
  info "This can take a couple of minutes the first time while Docker"
  info "downloads the base image and installs Python packages."
  blank

  cd "$PROJECT_DIR"
  $COMPOSE_CMD up -d --build

  blank
  ok "Container started"
}

# =============================================================================
# STEP 4 — Wait for the app to respond
# =============================================================================
wait_for_app() {
  local port
  port=$(grep -E "^APP_PORT=" "$ENV_FILE" 2>/dev/null \
         | cut -d= -f2 | tr -d '"' | tr -d "'" | tr -d ' ' || true)
  [[ -z "$port" ]] && port="8095"

  banner "Waiting for App to Start"
  blank

  local max_wait=60 elapsed=0 step=3

  if command -v curl &>/dev/null; then
    while [[ $elapsed -lt $max_wait ]]; do
      if curl -sf --max-time 2 "http://localhost:${port}/login" &>/dev/null 2>&1; then
        ok "App is responding on port ${port}"
        return 0
      fi
      sleep "$step"
      elapsed=$(( elapsed + step ))
      printf "\r  Waiting... %ds/%ds " "$elapsed" "$max_wait"
    done
    printf "\n"
    warn "App did not respond within ${max_wait}s."
    info "It may still be starting up.  Check with:  $COMPOSE_CMD logs -f"
  else
    info "curl not found — pausing 10 seconds for the container to start..."
    sleep 10
    ok "Container should be ready (curl unavailable for health check)"
  fi
}

# =============================================================================
# STEP 5 — Success banner
# =============================================================================
print_success() {
  local port lan_ip
  port=$(grep -E "^APP_PORT=" "$ENV_FILE" 2>/dev/null \
         | cut -d= -f2 | tr -d '"' | tr -d "'" | tr -d ' ' || true)
  [[ -z "$port" ]] && port="8095"
  lan_ip="$(_local_ip)"

  blank
  printf "%s%s╔══════════════════════════════════════╗%s\n" "$GREEN" "$BOLD" "$NC"
  printf "%s%s║  Net Profile Manager is live!  ║%s\n" "$GREEN" "$BOLD" "$NC"
  printf "%s%s╚══════════════════════════════════════╝%s\n" "$GREEN" "$BOLD" "$NC"
  blank
  printf "  %sOpen in your browser:%s\n"               "$BOLD" "$NC"
  printf "  %s  http://localhost:%s%s\n"                "$BLUE" "$port" "$NC"
  blank
  printf "  %sFrom your phone (same network or VPN):%s\n"  "$BOLD" "$NC"
  printf "  %s  http://%s:%s%s\n"                      "$BLUE" "$lan_ip" "$port" "$NC"
  blank
  printf "  %sFirst steps after opening the app:%s\n"  "$BOLD" "$NC"
  printf "    1. Enter your Admin PIN to log in\n"
  printf "    2. Devices  → Refresh from Omada  (load your device list)\n"
  printf "    3. Profiles → Create a profile  (e.g. Kids, Tablets)\n"
  printf "    4. Devices  → Add devices to the profile\n"
  printf "    5. Profile page → Pause or Resume the whole profile\n"
  blank
  printf "  %sUseful commands:%s\n"                    "$BOLD" "$NC"
  printf "    View logs :  %s\n"                       "$COMPOSE_CMD logs -f"
  printf "    Stop      :  %s\n"                       "$COMPOSE_CMD stop"
  printf "    Restart   :  %s\n"                       "$COMPOSE_CMD restart"
  printf "    Reconfigure: ./scripts/setup.sh\n"
  blank
}

# =============================================================================
# Main
# =============================================================================
main() {
  blank
  printf "%s%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n" "$BOLD" "$BLUE" "$NC"
  printf "%s%s   Net Profile Manager — Setup      %s\n" "$BOLD" "$BLUE" "$NC"
  printf "%s%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n" "$BOLD" "$BLUE" "$NC"
  blank

  check_prerequisites
  configure
  deploy
  wait_for_app
  print_success
}

main "$@"
