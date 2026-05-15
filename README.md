# Amazon BSR Dashboard — Tejas Jadhav (KDP Author)

Live dashboard tracking Amazon Best Seller Ranks across **5 books**, **3 formats**, and **15 countries**, updated daily via GitHub Actions.

## Setup (One-Time)

### 1. Create a GitHub Repository
```bash
cd kdp-dashboard
git init
git add .
git commit -m "Initial KDP BSR Dashboard"
git remote add origin https://github.com/YOUR_USERNAME/kdp-bsr-dashboard.git
git push -u origin main
```

### 2. Enable GitHub Pages
- Go to your repo → **Settings** → **Pages**
- Source: **GitHub Actions**
- Save

### 3. Enable GitHub Actions Permissions
- Go to **Settings** → **Actions** → **General**
- Under "Workflow permissions" → select **Read and write permissions**
- Save

The dashboard will be live at: `https://YOUR_USERNAME.github.io/kdp-bsr-dashboard/`

---

## Updating Rankings

### Option A: Manual (Recommended for US — enter ranks you see on KDP)
```bash
python scripts/manual_update.py
# Follow the prompts → enter country + BSR ranks
git add data/rankings.json
git commit -m "Update US BSR rankings 2026-05-16"
git push
```

### Option B: Automated Scraper (runs daily via GitHub Actions)
- Runs at **2 AM UTC (7:30 AM IST)** every day
- Tries to scrape all 15 Amazon country stores
- Falls back to last known data if blocked
- Trigger manually: GitHub repo → **Actions** → **Update BSR Rankings Daily** → **Run workflow**

---

## Adding Rankings for a Specific Country
```bash
python scripts/manual_update.py --country UK
python scripts/manual_update.py --country IN
python scripts/manual_update.py --country AU --date 2026-05-16
```

---

## Adding a New Book

Edit `data/books.json` and add an entry to the `books` array. Then run the scraper or manual update.

---

## Files
| File | Purpose |
|------|---------|
| `index.html` | Dashboard (GitHub Pages) |
| `data/books.json` | Book catalog with ASINs |
| `data/rankings.json` | Current + historical BSR data |
| `scripts/scrape_bsr.py` | Auto-scraper (runs in GitHub Actions) |
| `scripts/manual_update.py` | Manual rank entry tool |
| `.github/workflows/update_rankings.yml` | Daily automation |

---

## Books Tracked

| # | Title | Kindle | Paperback | Hardcover |
|---|-------|--------|-----------|-----------|
| ⭐ | Claude AI for Finance Professionals | B0GSX73KF6 | B0GV2SS77G | B0GVJPXVP8 |
| 2 | AI Prompts for Financial Analysis (100+) | B0GS5RL6XS | 9357823662 | — |
| 3 | The Wealth Code of Chhatrapati Shivaji Maharaj | B0D8R41W2F | B0GWWG34W6 | — |
| 4 | Stop Losing Money | B0G7YSZZJM | B0GWHZLVK8 | — |
| 5 | AI Prompts — Equity Research Hardcover | — | — | B0GSBV7QX9 |
