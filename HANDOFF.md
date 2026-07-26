# HANDOFF — BSR Dashboard (kdp-dashboard → github.com/tejasgjadhav/BSR)

## Goal
Live BSR dashboard (https://tejasgjadhav.github.io/BSR/) was frozen at "Jul 17".
Root cause: Amazon hardened bot detection ~Jul 17 — `curl_cffi` (TLS impersonation,
no JS) now gets the "Continue shopping" interstitial instead of the product page,
from BOTH GitHub Actions and residential IPs. Every daily scrape failed with
"Bot detection", but `continue-on-error: true` kept the workflow green, so the
site silently stale-served Jul-17 data.

## Fix (DONE, committed locally, PUSH PENDING)
Swapped fetch `curl_cffi` → **Playwright headless Chrome** that clicks through the
"Continue shopping" interstitial. Proven: headless Chrome pulls live BSR
(US #132,394). Runs LOCALLY via launchd (residential IP + real browser gets through).

Files changed (commit f9a971c + merge 69f310f):
- `scripts/scrape_bsr.py` — `_get_context()`/`fetch_html()`/`close_browser()`;
  fetch swapped; kept remote's `block_signatures` secondary check + `audit_log`.
- `scripts/requirements.txt` — curl_cffi → playwright.
- `scripts/setup_local.sh` — also runs `playwright install chromium`.
- `.github/workflows/update_rankings.yml` — disabled dead daily cron (was fake-green).

IMPORTANT: local was STALE vs remote. Pulled + merged (did NOT force-push) —
recovered remote's audit_log feature, 10 book covers, full history, deploy_pages.yml.

## Deploy path
Local push (user creds, NOT Actions GITHUB_TOKEN) → triggers `deploy_pages.yml` →
site redeploys. `daily_update.sh` does pull→scrape→commit→push. `setup_local.sh`
installs launchd agent `com.tejasgjadhav.bsr-update` (daily 8AM local + RunAtLoad).

## Remaining steps (user approved "do both")
1. [ ] `git push origin main` (pushes merge + code + fresh rankings.json) → flips site Jul17→Jul21.
2. [ ] `bash scripts/setup_local.sh` → install launchd (RunAtLoad triggers an immediate run).
3. [ ] Verify: deploy_pages.yml run succeeds; live site shows "Jul 21".

## FIXED (2026-07-26) — non-English stores returned no ranks
Two bugs, both fixed in scrape_bsr.py:
1. Interstitial click was English-only. Now locale-agnostic: `_is_interstitial()`
   detects the block in any locale (phrase list + short-body), clicks the primary
   button, then RE-NAVIGATES to the product URL (non-US "continue" buttons land on
   the store homepage, not the product).
2. ROOT CAUSE of missing DE/FR/ES/IT ranks: an en-US browser context gets a
   STRIPPED page (no Best-Sellers-Rank section) from non-US stores. Fix: one
   context PER locale (`DOMAIN_LOCALE` map, `_get_context(locale)`), passed from
   `scrape_bsr` by domain. Verified: DE paperback #90,150 in Bücher, DE hardcover
   #93 in Wirtschaftliches Wachstum now fetch. (DE kindle + EN-book-on-.fr are
   genuinely unranked — no rank label on page — correctly reported "BSR not found".)

Spanish edition audit (2026-07-26): claude_ai_finance_es (country_asins US-only,
ASINs B0H57YSP56/B0H9B6HXK2/B0H99G7KFX). Checked all 3 formats on BOTH .com and
.es with correct locale — pages load fully (correct titles, ~1.1MB) but carry NO
Best-Sellers-Rank section at all → Amazon has no BSR posted yet (not a fetch/parse
bug; same ASIN on .es returns the right book, so no ASIN mismatch). If it sold
today, BSR lags sales by up to a few hours; daily scraper will pick it up once
Amazon posts it. "BSR not found" here is HONEST/correct, not a failure.

Still open (minor): DE-only books also scrape 17 domains via base_asin fallback,
producing cross-listed junk ranks (German book on .com). Fallback is intentional
for EN editions sharing one ASIN across EN stores — don't remove blindly.

## STATUS 2026-07-26 15:18 UTC — locale fix run complete, PUSHED
Full run with per-locale fix: Success 49 (was 24-31), Failed 287 (mostly genuine
"BSR not found" on stores where a book isn't ranked). German now works:
pape/DE #90,150 in Bücher, hard/DE #93. Spanish (claude_ai_finance_es): NO ranks
(Amazon hasn't posted BSR yet — honest, not a bug). audit_log + history intact.
NOTE: some headline ranks are CATEGORY sub-ranks (e.g. hard/DE #93, hard/CA #60,
hard/BR #5) because the overall store rank is absent for that format — parser
takes bsr_data[0]; all_ranks has the full breakdown. Pre-existing behavior.

## Env / gotchas
- Playwright + chromium installed under /usr/bin/python3 (system). launchd plist PATH
  includes /usr/bin so `python3` resolves; uses `channel='chrome'` (system Chrome present).
- Re-scrape on full base: 31 OK / 305 fail, **146 "Bot detection"** on secondary
  markets (rate-blocking from 336 back-to-back hits). Primary markets (US) fresh;
  blocked countries retain last-good rank. FUTURE: throttle/space requests to cut this.
- rankings.json backups: scratchpad/rankings.merged.backup.json (pre-rescrape).
- `scripts/daily_update.log` is untracked runtime log (daily_update.sh only commits rankings.json).
