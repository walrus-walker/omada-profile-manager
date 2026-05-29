#!/usr/bin/env bash
# apply-env.sh
# Copy a named .env.<environment> file to .env and validate required variables.
#
# Usage:
#   ./scripts/apply-env.sh            # defaults to "desktop"
#   ./scripts/apply-env.sh desktop    # copies .env.desktop -> .env
#   ./scripts/apply-env.sh staging    # copies .env.staging -> .env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ENV_NAME="${1:-desktop}"
SOURCE_FILE="$PROJECT_DIR/.env.$ENV_NAME"
TARGET_FILE="$PROJECT_DIR/.env"

# Required variables that must be present and non-empty in the source file
REQUIRED_VARS=(
    OMADA_BASE_URL
    OMADA_CONTROLLER_ID
    OMADA_CLIENT_ID
    OMADA_CLIENT_SECRET
    OMADA_SITE_ID
    APP_ADMIN_PIN
    APP_SECRET_KEY
    DATABASE_PATH
)

echo "=========================================="
echo "  Net Profile Manager — apply-env"
echo "=========================================="
echo ""
echo "Environment : $ENV_NAME"
echo "Source file : $SOURCE_FILE"
echo "Target file : $TARGET_FILE"
echo ""

# Confirm source file exists
if [[ ! -f "$SOURCE_FILE" ]]; then
    echo "ERROR: Source file not found: $SOURCE_FILE"
    echo ""
    echo "Create it first:"
    echo "  cp $PROJECT_DIR/.env.example $SOURCE_FILE"
    echo "  nano $SOURCE_FILE"
    exit 1
fi

# Validate required variables
echo "Checking required variables..."
MISSING=0
for VAR in "${REQUIRED_VARS[@]}"; do
    # Match lines like VAR=something (non-empty value)
    if grep -qE "^${VAR}=.+" "$SOURCE_FILE"; then
        echo "  [OK] $VAR"
    else
        echo "  [MISSING or EMPTY] $VAR"
        MISSING=1
    fi
done

if [[ $MISSING -eq 1 ]]; then
    echo ""
    echo "ERROR: One or more required variables are missing or empty in $SOURCE_FILE"
    echo "       Edit the file and fill in all required values, then run this script again."
    exit 1
fi

echo ""
echo "All required variables are present."
echo ""

# Backup any existing .env
if [[ -f "$TARGET_FILE" ]]; then
    BACKUP="${TARGET_FILE}.bak.$(date +%Y%m%d%H%M%S)"
    cp "$TARGET_FILE" "$BACKUP"
    echo "Backed up existing .env to: $BACKUP"
fi

# Copy and lock down permissions
cp "$SOURCE_FILE" "$TARGET_FILE"
chmod 600 "$TARGET_FILE"

echo "Created .env from .env.$ENV_NAME"
echo ""
echo "=========================================="
echo "  Next steps"
echo "=========================================="
echo ""
echo "  docker compose up -d"
echo "  docker compose logs -f"
echo ""
echo "  App: http://localhost:8095"
echo ""
