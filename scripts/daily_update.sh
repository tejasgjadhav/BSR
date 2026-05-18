#!/bin/bash
# Daily BSR scraper — runs on Mac, pushes to GitHub
# Scheduled via crontab to run at 8:00 AM IST daily

set -e

REPO="/Users/sayali/files/kdp-dashboard"
LOG="$REPO/scripts/daily_update.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$DATE] Starting daily BSR update..." >> "$LOG"

cd "$REPO"

# Pull latest in case of any remote changes
git pull --no-rebase --quiet

# Run scraper
python3 scripts/scrape_bsr.py >> "$LOG" 2>&1

# Commit and push
git add data/rankings.json
if git diff --staged --quiet; then
    echo "[$DATE] No changes to commit." >> "$LOG"
else
    git commit -m "chore: update BSR rankings $(date -u '+%Y-%m-%d %H:%M UTC')"
    git push
    echo "[$DATE] Pushed rankings to GitHub." >> "$LOG"
fi

echo "[$DATE] Done." >> "$LOG"

# Keep log to last 500 lines
tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
