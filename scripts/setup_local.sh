#!/bin/bash
# One-time local setup for BSR auto-update.
# Creates a macOS LaunchAgent that runs the scraper:
#   - Every time you log in
#   - Daily at 8:00 AM (local time)
#
# Usage:
#   bash scripts/setup_local.sh
#
# Requires: Python 3, git configured with push access to the repo.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"

echo ""
echo "=== BSR Local Auto-Update Setup ==="
echo "Repo : $REPO"
echo "Script: $SCRIPT_DIR/daily_update.sh"
echo ""

# --- Install Python deps ---
echo "Installing Python dependencies..."
pip3 install -q -r "$SCRIPT_DIR/requirements.txt"
echo "  Done."

# --- Make scripts executable ---
chmod +x "$SCRIPT_DIR/daily_update.sh"

# --- Create macOS LaunchAgent ---
PLIST_NAME="com.tejasgjadhav.bsr-update"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCRIPT_DIR/daily_update.sh</string>
    </array>

    <!-- Run on every login AND at the scheduled time -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Daily at 8:00 AM local time -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/daily_update.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/daily_update.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>
</dict>
</plist>
PLIST

echo "Created: $PLIST_PATH"

# --- Load the agent ---
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "  Runs: on every login + daily at 8:00 AM"
echo "  Logs: tail -f $SCRIPT_DIR/daily_update.log"
echo ""
echo "Useful commands:"
echo "  Run now  : bash $SCRIPT_DIR/daily_update.sh"
echo "  View log : tail -f $SCRIPT_DIR/daily_update.log"
echo "  Remove   : launchctl unload $PLIST_PATH && rm $PLIST_PATH"
echo ""
