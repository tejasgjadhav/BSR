#!/usr/bin/env python3
"""
Amazon BSR (Best Seller Rank) Scraper for KDP Dashboard
Scrapes BSR data from Amazon product pages for 15 countries.
Run daily via GitHub Actions.
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import re
from datetime import datetime, timezone
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

HEADERS_LIST = [
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
    },
    {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    },
]

AMAZON_DOMAINS = {
    'US': 'www.amazon.com',
    'UK': 'www.amazon.co.uk',
    'IN': 'www.amazon.in',
    'CA': 'www.amazon.ca',
    'AU': 'www.amazon.com.au',
    'DE': 'www.amazon.de',
    'FR': 'www.amazon.fr',
    'IT': 'www.amazon.it',
    'ES': 'www.amazon.es',
    'JP': 'www.amazon.co.jp',
    'BR': 'www.amazon.com.br',
    'MX': 'www.amazon.com.mx',
    'NL': 'www.amazon.nl',
    'SE': 'www.amazon.se',
    'PL': 'www.amazon.pl',
}


def get_random_headers():
    return dict(random.choice(HEADERS_LIST))


def normalize_rank_number(s):
    """
    Convert any locale rank string to int.
    Handles: 97,448 (US)  118.877 (DE/IT)  118 877 (FR/CA space-sep)
    Strategy: strip all non-digits.
    """
    return int(re.sub(r'[^\d]', '', s))


def parse_bsr_text(text):
    """
    Parse ALL rank entries from BSR text block.

    Handles English:  #97,448 in Kindle Store / #5 in Investing Portfolio Management
    Handles German:   Nr. 118.877 in Bücher / Nr. 61 in Generative KI
    Handles French:   n°118 877 en Livres / nº 61 en IA Générative
    Handles Italian:  n. 118.877 in Libri
    Handles Japanese: 売れ筋ランキング - X位
    Handles Spanish:  nº 118.877 en Libros / nº 61 en IA Generativa
    """
    # Remove noise like "( See Top 100 in Books )" / "( Siehe Top 100 in Bücher )"
    clean = re.sub(r'\([^)]{0,60}(?:Top|top)\s+\d+[^)]*\)', '', text)
    clean = re.sub(r'\([^)]{0,60}(?:Voir|voir|Vedi|vedi|Ver|ver)\s+[^)]*\)', '', clean)

    results = []
    seen = set()

    # Remove noise: "( See Top 100 in Books )" style
    clean = re.sub(r'\([^)]{0,80}(?:See|Voir|Vedi|Ver|Siehe)\s+Top[^)]*\)', '', clean)

    # ── Pattern A: #number in Category  (US/UK/IN/CA/AU + EN pages of DE/FR/IT/ES)
    for m in re.finditer(
        r'#\s*([\d,]+)\s+in\s+((?:[\w&\u2019/()\-\u2013\s]){3,60}?)(?=\s*(?:#|\d{1,3}\s+in\s|\Z|\n))',
        clean, re.UNICODE
    ):
        rank = normalize_rank_number(m.group(1))
        cat  = m.group(2).strip().strip('(').strip()
        if cat and not re.search(r'See\s+Top', cat, re.I) and rank > 0:
            key = (rank, cat.lower()[:40])
            if key not in seen:
                seen.add(key)
                results.append({'rank': rank, 'category': cat})

    # ── Pattern A2: bare "NUMBER in Category" (EN-language DE/FR pages without #)
    # Triggered after "Best Sellers Rank:" line
    bare_pat = re.compile(
        r'(?<!\w)([\d][\d,]*)\s+in\s+((?:[A-Z][\w&/()\-\s]){3,60}?)(?=\s*(?:\d{1,3}\s+in\s|Customer|$|\n))',
        re.UNICODE
    )
    for m in bare_pat.finditer(clean):
        try:
            rank = normalize_rank_number(m.group(1))
        except Exception:
            continue
        if rank == 0 or rank > 10_000_000:
            continue
        cat = m.group(2).strip().strip('(').strip()
        if len(cat) < 3 or re.search(r'See\s+Top', cat, re.I):
            continue
        key = (rank, cat.lower()[:40])
        if key not in seen:
            seen.add(key)
            results.append({'rank': rank, 'category': cat})

    if results:
        return results

    # ── Pattern B: European locale  Nr./n°/nº/n. NUMBER in/en CATEGORY
    for m in re.finditer(
        r'(?:Nr\.|n[°º]|n\.)\s*([\d.,\s]+?)\s+(?:in|en)\s+((?:[\w&\u00C0-\u024F\u4E00-\u9FFF()\-\s/&]){3,70}?)(?=\s*(?:Nr\.|n[°º]|n\.|$|\n|\())',
        clean, re.UNICODE | re.IGNORECASE
    ):
        raw_num = m.group(1).strip()
        rank = normalize_rank_number(raw_num)
        if rank == 0 or rank > 10_000_000:
            continue
        cat = m.group(2).strip().strip('(').strip()
        if len(cat) < 2 or re.search(r'^\d+$', cat):
            continue
        key = (rank, cat.lower()[:40])
        if key not in seen:
            seen.add(key)
            results.append({'rank': rank, 'category': cat})

    return results


# BSR trigger keywords across all Amazon locales
BSR_KEYWORDS = [
    'Best Sellers Rank', 'Bestsellers Rank', 'Amazon Best Sellers Rank',  # EN
    'Amazon Bestseller-Rang', 'Bestseller-Rang',                           # DE
    'Meilleures ventes',  'Classement des meilleures ventes',              # FR
    'Posizione nella classifica', 'Classifica Bestseller',                 # IT
    'Posición en los más vendidos', 'Los más vendidos',                    # ES
    'Mais vendidos',                                                        # PT/BR
    'Más vendidos',                                                         # MX
    'ランキング', '売れ筋ランキング',                                       # JP
    'Bestseller-rang', 'Bestsellerrang',                                    # NL/SE/PL
]


def has_bsr_keyword(text):
    return any(kw.lower() in text.lower() for kw in BSR_KEYWORDS)


def extract_bsr_from_html(soup):
    """Extract ALL BSR rank entries using multiple fallback strategies, all locales."""
    bsr_data = []

    # Strategy 1: Detail bullets wrapper (modern Amazon layout, all locales)
    detail_bullets = soup.find('div', {'id': 'detailBulletsWrapper_feature_div'})
    if detail_bullets:
        for li in detail_bullets.find_all('li'):
            text = li.get_text(separator=' ', strip=True)
            if has_bsr_keyword(text):
                bsr_data = parse_bsr_text(text)
                if bsr_data:
                    return bsr_data

    # Strategy 2: Product details table (used on DE, FR, IT, ES...)
    for table_id in ['productDetails_detailBullets_sections1', 'productDetails_techSpec_section_1',
                     'productDetails_db_sections1']:
        table = soup.find('table', {'id': table_id})
        if table:
            for row in table.find_all('tr'):
                th = row.find('th')
                td = row.find('td')
                if th and td and has_bsr_keyword(th.get_text()):
                    bsr_data = parse_bsr_text(td.get_text(separator=' ', strip=True))
                    if bsr_data:
                        return bsr_data

    # Strategy 3: Any span/li containing a BSR keyword
    for tag in soup.find_all(['span', 'li']):
        text = tag.get_text(separator=' ', strip=True)
        if has_bsr_keyword(text) and len(text) < 2000:
            bsr_data = parse_bsr_text(text)
            if bsr_data:
                return bsr_data

    # Strategy 4: Full page text scan — find BSR block and parse up to 800 chars
    page_text = soup.get_text(separator=' ')
    for kw in BSR_KEYWORDS:
        idx = page_text.find(kw)
        if idx != -1:
            block = page_text[idx:idx+800]
            bsr_data = parse_bsr_text(block)
            if bsr_data:
                return bsr_data
            # Strategy 4b: direct bare-number extraction from the block
            # Handles: "118,877 in Books   61 in Generative AI   90 in Management..."
            bsr_data = _extract_bare_numbers(block)
            if bsr_data:
                return bsr_data

    return bsr_data


def _extract_bare_numbers(block):
    """
    Last-resort parser for EN-language responses from non-US stores.
    Finds patterns like: 118,877 in Books  61 in Generative AI
    """
    # Strip noise parentheses
    clean = re.sub(r'\([^)]{0,100}\)', ' ', block)
    results = []
    seen = set()
    pat = re.compile(
        r'\b([\d][\d,\.]*)\s+in\s+([A-Z][A-Za-z0-9 &/()\-]{2,50}?)(?=\s{2,}|\d|\Z|Customer|$)',
        re.UNICODE
    )
    for m in pat.finditer(clean):
        try:
            rank = normalize_rank_number(m.group(1))
        except Exception:
            continue
        if rank <= 0 or rank > 10_000_000:
            continue
        cat = m.group(2).strip().rstrip()
        if len(cat) < 3:
            continue
        key = (rank, cat.lower()[:40])
        if key not in seen:
            seen.add(key)
            results.append({'rank': rank, 'category': cat})
    return results


def scrape_bsr(asin, domain, retries=2):
    """Scrape BSR from an Amazon product page."""
    url = f"https://{domain}/dp/{asin}"

    for attempt in range(retries + 1):
        try:
            if attempt > 0:
                wait = random.uniform(5, 12)
                logger.info(f"      Retry {attempt}/{retries}, waiting {wait:.1f}s...")
                time.sleep(wait)

            headers = get_random_headers()
            session = requests.Session()
            response = session.get(url, headers=headers, timeout=20, allow_redirects=True)

            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'lxml')

                # Check if we hit a CAPTCHA/bot detection page
                title = soup.find('title')
                if title and ('robot' in title.text.lower() or 'captcha' in title.text.lower() or 'sorry' in title.text.lower()):
                    logger.warning(f"      Bot detection on attempt {attempt + 1}")
                    continue

                bsr_data = extract_bsr_from_html(soup)

                if bsr_data:
                    return {
                        'success': True,
                        'primary_rank': bsr_data[0]['rank'],
                        'primary_category': bsr_data[0]['category'],
                        'all_ranks': bsr_data,
                        'url': url
                    }
                else:
                    logger.warning(f"      No BSR found for {asin} on {domain}")
                    return {'success': False, 'error': 'BSR not found', 'url': url}

            elif response.status_code == 404:
                logger.info(f"      Product {asin} not available on {domain}")
                return {'success': False, 'error': 'Not available (404)'}
            elif response.status_code == 503:
                logger.warning(f"      Bot blocked (503) attempt {attempt + 1}")
                if attempt < retries:
                    continue
                return {'success': False, 'error': 'Bot blocked (503)'}
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}

        except requests.exceptions.Timeout:
            if attempt < retries:
                continue
            return {'success': False, 'error': 'Timeout'}
        except Exception as e:
            logger.error(f"      Error: {e}")
            if attempt < retries:
                continue
            return {'success': False, 'error': str(e)}

    return {'success': False, 'error': 'All retries failed'}


def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_rankings():
    """Main update loop — scrapes all books × formats × countries."""
    books_data = load_json(os.path.join(DATA_DIR, 'books.json'))
    rankings = load_json(os.path.join(DATA_DIR, 'rankings.json'))

    timestamp = datetime.now(timezone.utc).isoformat()
    date_key = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    rankings.setdefault('history', {})
    rankings.setdefault('current', {})
    rankings['last_updated'] = timestamp

    success_count = 0
    fail_count = 0

    for book in books_data['books']:
        book_id = book['id']
        logger.info(f"\n{'='*60}")
        logger.info(f"Book: {book['title']}")
        logger.info(f"{'='*60}")

        rankings['current'].setdefault(book_id, {})
        rankings['history'].setdefault(book_id, {})

        for fmt_name, fmt_data in book.get('formats', {}).items():
            base_asin = fmt_data.get('asin')
            if not base_asin:
                continue

            rankings['current'][book_id].setdefault(fmt_name, {})
            rankings['history'][book_id].setdefault(fmt_name, {})

            logger.info(f"\n  [{fmt_name.upper()}] ASIN: {base_asin}")

            country_asins = fmt_data.get('country_asins', {})

            for country_code, domain in AMAZON_DOMAINS.items():
                # Use country-specific ASIN if mapped, else default
                asin = country_asins.get(country_code, base_asin)
                if asin == 'N/A':
                    continue

                logger.info(f"    {country_code} ({domain}) ...")
                result = scrape_bsr(asin, domain)

                if result['success']:
                    rankings['current'][book_id][fmt_name][country_code] = {
                        'rank': result['primary_rank'],
                        'category': result['primary_category'],
                        'all_ranks': result['all_ranks'],
                        'timestamp': timestamp,
                        'asin': asin,
                        'url': result.get('url')
                    }

                    # Append to history
                    hist = rankings['history'][book_id][fmt_name].setdefault(country_code, [])
                    hist.append({'date': date_key, 'rank': result['primary_rank'], 'category': result['primary_category']})
                    rankings['history'][book_id][fmt_name][country_code] = hist[-90:]  # 90 days

                    logger.info(f"    OK: #{result['primary_rank']:,} in {result['primary_category']}")
                    success_count += 1
                else:
                    logger.warning(f"    FAIL: {result['error']}")
                    fail_count += 1
                    # Preserve existing data, add error note
                    existing = rankings['current'][book_id][fmt_name].get(country_code, {})
                    existing['last_error'] = result['error']
                    existing['error_timestamp'] = timestamp
                    rankings['current'][book_id][fmt_name][country_code] = existing

                # Respectful delay between requests
                time.sleep(random.uniform(3, 7))

    save_json(os.path.join(DATA_DIR, 'rankings.json'), rankings)
    logger.info(f"\nDone! Success: {success_count}, Failed: {fail_count}")
    return rankings


if __name__ == '__main__':
    update_rankings()
