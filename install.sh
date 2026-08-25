#!/bin/sh
# NoClick Community installer.
#
#   curl -fsSL https://noclick.com/install.sh | sh
#
# Fetches the source, generates this instance's secrets, and starts the stack.
# Re-running it updates an existing install in place, keeping the database, the
# uploaded files and the secrets — including the credential-encryption key,
# without which stored integration credentials cannot be read.
#
# Everything is overridable from the environment, because a one-liner that can
# only do one thing is not much of an install:
#
#   NOCLICK_DIR=/srv/noclick     where the source and .env live
#   NOCLICK_REF=v1.2.3           branch or tag to install (default: main)
#   NOCLICK_REPO=<git url>       source to clone from
#   NOCLICK_APP_URL=https://…    public URLs, if this is not a laptop
#   NOCLICK_NO_START=1           set everything up, start nothing

set -eu

REPO="${NOCLICK_REPO:-https://github.com/noclickapp/noclick.git}"
REF="${NOCLICK_REF:-main}"
DIR="${NOCLICK_DIR:-$HOME/noclick}"

red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
say() { printf '\033[1m→\033[0m %s\n' "$*"; }
die() { red "$*"; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ── Prerequisites ────────────────────────────────────────────────────────────
# Deliberately no silent `curl … | sh` of Docker's own installer: this script
# was already piped into a shell once, and doing it twice on someone's behalf,
# as root, is a step too far. The command to run is printed instead.
have docker || die "Docker is required.
  Linux:  curl -fsSL https://get.docker.com | sh
  macOS:  https://docs.docker.com/desktop/install/mac-install/
  Then run this installer again."

docker info >/dev/null 2>&1 || die "Docker is installed but not running (or this user cannot reach it).
  Start Docker, or add yourself to the docker group: sudo usermod -aG docker \"\$USER\""

if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif have docker-compose; then
    COMPOSE="docker-compose"
else
    die "Docker Compose v2 is required — see https://docs.docker.com/compose/install/"
fi

have git || die "git is required to fetch and update the source."
have openssl || die "openssl is required to generate this instance's secrets."

# ── Source ───────────────────────────────────────────────────────────────────
if [ -d "$DIR/.git" ]; then
    say "Updating $DIR"
    git -C "$DIR" fetch --quiet origin "$REF"
    # Reset rather than merge: local edits to tracked files are not a supported
    # upgrade path, and a half-merged tree is a worse place to be than a clean
    # one. .env is untracked and survives.
    git -C "$DIR" checkout --quiet --force FETCH_HEAD
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
    die "$DIR already exists and is not a NoClick checkout. Set NOCLICK_DIR to somewhere else."
else
    say "Fetching NoClick into $DIR"
    git clone --quiet --depth 1 --branch "$REF" "$REPO" "$DIR" \
        || die "Could not clone $REPO ($REF)."
fi

cd "$DIR"

# ── Configuration ────────────────────────────────────────────────────────────
say "Generating any missing secrets"
sh ./scripts/noclick-setup.sh >/dev/null
chmod 600 .env

if [ "${NOCLICK_NO_START:-}" = "1" ]; then
    say "Set up in $DIR. Start it with: cd $DIR && $COMPOSE up -d --build"
    exit 0
fi

# ── Start ────────────────────────────────────────────────────────────────────
say "Building and starting (the first build takes a few minutes)"
$COMPOSE up -d --build

APP_URL="$(sed -n 's/^NOCLICK_APP_URL=//p' .env | head -1)"
: "${APP_URL:=http://localhost:3000}"

say "Waiting for the app to answer"
i=0
until [ "$i" -ge 90 ]; do
    if curl -fsS -o /dev/null "$APP_URL" 2>/dev/null; then
        printf '\n\033[32m✓\033[0m NoClick is running at %s\n\n' "$APP_URL"
        printf '  Create the first account there; sign-ups are confirmed without\n'
        printf '  email until you configure SMTP.\n\n'
        printf '  Source and configuration:  %s\n' "$DIR"
        printf '  Logs:                      cd %s && %s logs -f\n' "$DIR" "$COMPOSE"
        printf '  Stop:                      cd %s && %s down\n\n' "$DIR" "$COMPOSE"
        printf '  Back up %s/.env — CREDENTIALS_ENCRYPTION_KEY is in it, and\n' "$DIR"
        printf '  without that key a restored database cannot read any credential.\n'
        exit 0
    fi
    i=$((i + 1))
    sleep 2
done

red "The app did not answer at $APP_URL within three minutes."
red "The containers are still running; see what they say:"
red "  cd $DIR && $COMPOSE logs --tail 50"
exit 1
