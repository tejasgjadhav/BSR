#!/usr/bin/env python3
"""
Manual BSR Update Tool for KDP Dashboard
Run this locally to enter your Amazon bestseller ranks by hand.
Changes are saved to data/rankings.json — then commit & push to GitHub.

Usage:
    python scripts/manual_update.py
    python scripts/manual_update.py --country US
    python scripts/manual_update.py --country IN --date 2026-05-16
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

COUNTRY_FLAGS = {
    'US': '🇺🇸', 'UK': '🇬🇧', 'IN': '🇮🇳', 'CA': '🇨🇦',
    'AU': '🇦🇺', 'DE': '🇩🇪', 'FR': '🇫🇷', 'IT': '🇮🇹',
    'ES': '🇪🇸', 'JP': '🇯🇵', 'BR': '🇧🇷', 'MX': '🇲🇽',
    'NL': '🇳🇱', 'SE': '🇸🇪', 'PL': '🇵🇱', 'BE': '🇧🇪', 'IE': '🇮🇪',
}

FORMAT_EMOJIS = {'kindle': '📱', 'paperback': '📄', 'hardcover': '📗'}


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def prompt(msg, default=None):
    if default is not None:
        display = f"{msg} [{default}]: "
    else:
        display = f"{msg}: "
    val = input(display).strip()
    return val if val else default


def main():
    parser = argparse.ArgumentParser(description='Manually update Amazon BSR rankings')
    parser.add_argument('--country', default=None, help='Country code (US, UK, IN, ...)')
    parser.add_argument('--date', default=None, help='Date override YYYY-MM-DD (default: today)')
    args = parser.parse_args()

    books_data = load_json(os.path.join(DATA_DIR, 'books.json'))
    rankings_path = os.path.join(DATA_DIR, 'rankings.json')
    rankings = load_json(rankings_path) if os.path.exists(rankings_path) else {}

    rankings.setdefault('current', {})
    rankings.setdefault('history', {})

    print("\n" + "=" * 60)
    print("  🏆  Amazon BSR Manual Update — KDP Dashboard")
    print("=" * 60)

    # Select country
    if args.country:
        country = args.country.upper()
    else:
        print("\nAvailable countries:")
        for code, flag in COUNTRY_FLAGS.items():
            print(f"  {flag}  {code}")
        country = prompt("\nEnter country code", "US").upper()

    if country not in COUNTRY_FLAGS:
        print(f"Unknown country code: {country}")
        sys.exit(1)

    print(f"\nEntering ranks for {COUNTRY_FLAGS.get(country, '')} {country}")

    # Date
    if args.date:
        date_key = args.date
    else:
        date_key = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    timestamp = datetime.now(timezone.utc).isoformat()
    updated_count = 0

    print("\nFor each book format, enter the BSR rank number (e.g. 12345)")
    print("Press Enter to SKIP a format.\n")

    for book in books_data['books']:
        book_id = book['id']
        print(f"\n{'─'*60}")
        print(f"📚 {book['title']}")
        print(f"{'─'*60}")

        rankings['current'].setdefault(book_id, {})
        rankings['history'].setdefault(book_id, {})

        for fmt_name, fmt_data in book.get('formats', {}).items():
            asin = fmt_data.get('asin', 'N/A')
            emoji = FORMAT_EMOJIS.get(fmt_name, '')

            rank_str = prompt(f"  {emoji} {fmt_name.capitalize()} (ASIN: {asin}) — BSR rank")
            if not rank_str:
                continue

            try:
                rank = int(rank_str.replace('#', '').replace(',', '').strip())
            except ValueError:
                print("  Invalid rank, skipping.")
                continue

            category = prompt("  Category (e.g. 'AI & Machine Learning')", "General")

            rankings['current'][book_id].setdefault(fmt_name, {})
            rankings['history'][book_id].setdefault(fmt_name, {})

            rankings['current'][book_id][fmt_name][country] = {
                'rank': rank,
                'category': category,
                'all_ranks': [{'rank': rank, 'category': category}],
                'timestamp': timestamp,
                'asin': asin,
                'manual': True
            }

            hist = rankings['history'][book_id][fmt_name].setdefault(country, [])
            # Don't duplicate same day
            hist = [h for h in hist if h.get('date') != date_key]
            hist.append({'date': date_key, 'rank': rank, 'category': category})
            rankings['history'][book_id][fmt_name][country] = hist[-90:]

            print(f"  ✅ Saved: #{rank:,} in {category}")
            updated_count += 1

    if updated_count == 0:
        print("\nNo ranks entered. Nothing saved.")
        sys.exit(0)

    rankings['last_updated'] = timestamp
    save_json(rankings_path, rankings)

    print(f"\n{'='*60}")
    print(f"✅ {updated_count} rank(s) saved for {COUNTRY_FLAGS.get(country,'')} {country}")
    print(f"📁 File: {rankings_path}")
    print()
    print("Next steps to publish to GitHub:")
    print("  git add data/rankings.json")
    print(f"  git commit -m 'Update {country} BSR rankings {date_key}'")
    print("  git push")
    print("=" * 60)


if __name__ == '__main__':
    main()
