#!/bin/bash
# Daily BSR scraper — runs locally, commits and pushes updated rankings to GitHub.
# Scheduled via: bash scripts/setup_local.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
LOG="$SCRIPT_DIR/daily_update.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[$DATE] $*" | tee -a "$LOG"; }

log "Starting BSR update (repo: $REPO)"
cd "$REPO"

# Pull latest to avoid push conflicts
git pull --no-rebase --quiet 2>&1 || log "WARNING: git pull failed, continuing"

# Run scraper
if python3 scripts/scrape_bsr.py >> "$LOG" 2>&1; then
    log "Scraper finished"
else
    log "ERROR: scraper exited with code $?"
    exit 1
fi

# Commit and push only if rankings changed
git add data/rankings.json
if git diff --staged --quiet; then
    log "No changes to commit."
else
    git commit -m "chore: update BSR rankings $(date -u '+%Y-%m-%d')"
    if git push; then
        log "Pushed rankings to GitHub."
    else
        log "ERROR: git push failed"
        exit 1
    fi
fi

log "Done."

# Keep log trimmed to last 500 lines
tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
