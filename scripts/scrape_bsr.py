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
    'BE': 'www.amazon.com.be',
    'IE': 'www.amazon.ie',
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
    Parse ALL rank entries from BSR text block across ALL Amazon locales.

    Locale formats handled:
      EN (US/UK/IN/CA/AU):  #97,448 in Kindle Store · #5 in Investing Portfolio Management
      EN on non-US stores:  118,877 in Books · 62 in Financial Risk Management  (no # prefix)
      DE:  Nr. 118.877 in Bücher · Nr. 61 in Generative KI
      FR:  n° 193 en Intelligence artificielle générative
      IT:  n. 598 in Economia, affari e finanza (Libri) · classifica Bestseller di Amazon
      ES:  nº 32.764 en Libros · nº 61 en IA Generativa
      BR:  Nº 30.974 em Loja Kindle · Nº 74 em Computação, internet e mídia digital em inglês
      MX:  nº 86 en Finanzas Corporativas (uses # on EN response)
      NL:  #26,711 in Kindle Store (EN response)
    """
    # ── Step 1: Strip all noise parentheses
    # Removes: ( See Top 100 in Books ) / ( Conheça o Top 100 na categoria Loja Kindle ) / ( Siehe Top 100 )
    clean = re.sub(
        r'\([^)]{0,120}(?:See|Voir|Vedi|Ver|Siehe|Conhe[çc]a|Consulta|Top\s+100)[^)]*\)',
        ' ', text, flags=re.IGNORECASE
    )
    # Remove stray "Avaliações dos clientes" / "Customer reviews" trailing text
    for stop in ['Avalia', 'Customer reviews', 'Recensioni', 'Reseñas', 'Kundrezensionen', 'Avis client']:
        idx = clean.find(stop)
        if idx > 0:
            clean = clean[:idx]

    results = []
    seen = set()

    def add(rank, cat):
        cat = cat.strip().strip('(').strip().rstrip('(').strip()
        if not cat or len(cat) < 2 or rank <= 0 or rank > 10_000_000:
            return
        # Skip pure noise
        if re.search(r'(?:See|Voir|Top\s+\d+|^\d+$)', cat, re.I):
            return
        key = (rank, cat.lower()[:40])
        if key not in seen:
            seen.add(key)
            results.append({'rank': rank, 'category': cat})

    # ── Pattern A: #number in/em Category  (EN, NL, some MX)
    # Category can contain commas, accented chars, apostrophes
    for m in re.finditer(
        r'#\s*([\d,]+)\s+(?:in|em)\s+'
        r'([\w\u00C0-\u024F&\'\u2019/()\-\u2013, ]{3,80}?)'
        r'(?=\s*(?:#\s*\d|\d{1,3}\s+(?:in|em)\s+[A-Z\u00C0]|\Z|\n))',
        clean, re.UNICODE
    ):
        try: add(normalize_rank_number(m.group(1)), m.group(2))
        except: pass

    # ── Pattern B: bare NUMBER in/em Category (EN pages on DE/FR/UK/IT/BR stores, no # prefix)
    # e.g.: 118,877 in Books   62 in Financial Risk Management   131 in Managers' Guides
    # Lookahead: next entry starts with a number OR Nr./Nº OR 2+ spaces OR end
    for m in re.finditer(
        r'(?<!\d)([\d][\d,\.]*)\s+(?:in|em)\s+'
        r'([A-Z\u00C0-\u024F][A-Za-z\u00C0-\u024F0-9&\'\u2019/()\-, ]{2,70}?)'
        r'(?=\s*(?:Nr\.|[Nn][°º]|n\.)|\s{2,}|\s*(?:\d{1,6}\s+(?:in|em)\s+[A-Z\u00C0])|\Z|\n)',
        clean, re.UNICODE
    ):
        try:
            rank = normalize_rank_number(m.group(1))
            add(rank, m.group(2))
        except: pass

    if results:
        return results

    # ── Pattern C: Nr./n°/nº/Nº/n. NUMBER in/en/em CATEGORY  (DE/FR/ES/BR/IT native pages)
    # BR: Nº 30.974 em Computação, internet e mídia digital em inglês
    # DE: Nr. 118.877 in Bücher · Nr. 61 in Generative KI
    # ES: nº 32.764 en Libros
    # IT: n. 598 in Economia, affari e finanza (Libri)
    for m in re.finditer(
        r'(?:Nr\.|[Nn][°º]|n\.)\s*([\d.,\s]{1,15})\s+(?:in|en|em)\s+'
        r'([\w\u00C0-\u024F&\'\u2019/()\-, ]{3,80}?)'
        r'(?=\s*(?:Nr\.|[Nn][°º]|n\.|$|\n|\())',
        clean, re.UNICODE
    ):
        try:
            rank = normalize_rank_number(m.group(1).strip())
            add(rank, m.group(2))
        except: pass

    return results


# BSR trigger keywords across all Amazon locales
BSR_KEYWORDS = [
    # English
    'Best Sellers Rank', 'Bestsellers Rank', 'Amazon Best Sellers Rank',
    # German
    'Amazon Bestseller-Rang', 'Bestseller-Rang', 'Bestseller-Rang:',
    # French
    'Meilleures ventes', 'Classement des meilleures ventes',
    # Italian
    'Posizione nella classifica', 'Classifica Bestseller', 'classifica Bestseller',
    # Spanish
    'Posición en los más vendidos', 'Los más vendidos', 'más vendidos',
    # Portuguese / Brazil
    'Ranking dos mais vendidos', 'Mais vendidos', 'mais vendidos',
    # Mexico
    'Más vendidos', 'más vendidos',
    # Japanese
    'ランキング', '売れ筋ランキング', 'Amazon売れ筋ランキング',
    # Dutch / Swedish / Polish
    'Bestseller-rang', 'Bestsellerrang', 'Bästsäljare', 'Bestsellery',
    # Fallback
    'Bestseller Rang', 'Ranking',
]


def has_bsr_keyword(text):
    return any(kw.lower() in text.lower() for kw in BSR_KEYWORDS)


def extract_bsr_from_html(soup):
    """Extract ALL BSR rank entries using multiple fallback strategies, all locales."""
    bsr_data = []

    # Pre-compute full-page text once — has multi-space separators between elements,
    # which is critical for correctly parsing bare-number ranks (DE/IT/FR EN-response pages).
    # Single-spaced li.get_text() causes Pattern B to misparse "1,137 in Books" as
    # category="... 1," + rank=137. Full page text avoids this.
    page_text = soup.get_text(separator=' ')

    def parse_from_page(keyword_hint):
        """Find keyword in full-page text and parse the block from there."""
        # Try the exact keyword first, then any BSR keyword
        hints = [keyword_hint] if keyword_hint else []
        hints += [kw for kw in BSR_KEYWORDS if kw != keyword_hint]
        for kw in hints:
            idx = page_text.find(kw)
            if idx != -1:
                block = page_text[idx:idx + 800]
                data = parse_bsr_text(block)
                if data:
                    return data
                data = _extract_bare_numbers(block)
                if data:
                    return data
        return []

    # Strategy 1: Detail bullets wrapper (modern Amazon layout, all locales)
    # Use li only as a locator; parse from full-page text for correct multi-spacing.
    detail_bullets = soup.find('div', {'id': 'detailBulletsWrapper_feature_div'})
    if detail_bullets:
        for li in detail_bullets.find_all('li'):
            text = li.get_text(separator=' ', strip=True)
            if has_bsr_keyword(text):
                # Find which keyword matched so we can locate it in page_text
                matched_kw = next((kw for kw in BSR_KEYWORDS if kw.lower() in text.lower()), None)
                bsr_data = parse_from_page(matched_kw)
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
                    matched_kw = next((kw for kw in BSR_KEYWORDS if kw.lower() in th.get_text().lower()), None)
                    bsr_data = parse_from_page(matched_kw)
                    if bsr_data:
                        return bsr_data

    # Strategy 3: Any span/li containing a BSR keyword
    for tag in soup.find_all(['span', 'li']):
        text = tag.get_text(separator=' ', strip=True)
        if has_bsr_keyword(text) and len(text) < 2000:
            matched_kw = next((kw for kw in BSR_KEYWORDS if kw.lower() in text.lower()), None)
            bsr_data = parse_from_page(matched_kw)
            if bsr_data:
                return bsr_data

    # Strategy 4: Full page text scan — find BSR block and parse up to 800 chars
    for kw in BSR_KEYWORDS:
        idx = page_text.find(kw)
        if idx != -1:
            block = page_text[idx:idx + 800]
            bsr_data = parse_bsr_text(block)
            if bsr_data:
                return bsr_data
            bsr_data = _extract_bare_numbers(block)
            if bsr_data:
                return bsr_data

    return bsr_data


def _extract_bare_numbers(block):
    """
    Last-resort parser for EN-language responses from non-US stores.
    Finds patterns like: 118,877 in Books  61 in Generative AI  131 in Managers' Guides
    Handles apostrophes and special chars in category names.
    """
    # Strip noise parentheses like (See Top 100 in Books)
    clean = re.sub(r'\([^)]{0,100}\)', ' ', block)
    results = []
    seen = set()
    # Allow apostrophe \u2019 ' and extended chars in category names
    pat = re.compile(
        r'\b([\d][\d,\.]*)\s+in\s+([A-Z][A-Za-z0-9 &/()\'\u2019\-]{2,55}?)(?=\s{2,}|\s*\d|\Z|Customer|$)',
        re.UNICODE
    )
    for m in pat.finditer(clean):
        try:
            rank = normalize_rank_number(m.group(1))
        except Exception:
            continue
        if rank <= 0 or rank > 10_000_000:
            continue
        cat = m.group(2).strip()
        if len(cat) < 3:
            continue
        key = (rank, cat.lower()[:40])
        if key not in seen:
            seen.add(key)
            results.append({'rank': rank, 'category': cat})
    return results


# Title slugs for stores where /dp/ASIN doesn't render BSR in HTML
# Only physical formats (paperback/hardcover) work this way — Kindle eBooks are always JS-rendered on UK/ES
# Format: asin -> {domain -> title_slug}
TITLE_SLUGS = {
    # Claude AI Paperback
    'B0GV2SS77G': {
        'www.amazon.co.uk': 'Claude-Finance-Professionals-Institutional-Investment',
        'www.amazon.es':    'Claude-Finance-Professionals-Institutional-Investment',
    },
    # Claude AI Hardcover
    'B0GVJPXVP8': {
        'www.amazon.co.uk': 'Claude-Finance-Professionals-Institutional-Investment',
        'www.amazon.es':    'Claude-Finance-Professionals-Institutional-Investment',
    },
    # AI Prompts 100+ Paperback
    '9357823662': {
        'www.amazon.co.uk': 'AI-Prompts-Financial-Analysis-Practical',
        'www.amazon.es':    'AI-Prompts-Financial-Analysis-Practical',
    },
    # Shivaji Paperback
    'B0GWWG34W6': {
        'www.amazon.co.uk': 'Wealth-Code-Chhatrapati-Shivaji-Maharaj',
        'www.amazon.es':    'Wealth-Code-Chhatrapati-Shivaji-Maharaj',
    },
    # Stop Losing Money Paperback
    'B0GWHZLVK8': {
        'www.amazon.co.uk': 'Stop-Losing-Money-Stories-Private',
        'www.amazon.es':    'Stop-Losing-Money-Stories-Private',
    },
    # AI Prompts Equity Hardcover
    'B0GSBV7QX9': {
        'www.amazon.co.uk': 'AI-Prompts-Financial-Analysis-Practical',
        'www.amazon.es':    'AI-Prompts-Financial-Analysis-Practical',
    },
}


def build_urls(asin, domain):
    """Return list of URLs to try, full-title slug first if available."""
    urls = []
    slug = TITLE_SLUGS.get(asin, {}).get(domain)
    if slug:
        urls.append(f"https://{domain}/{slug}/dp/{asin}/ref=tmm_pap_swatch_0")
        urls.append(f"https://{domain}/{slug}/dp/{asin}")
    urls.append(f"https://{domain}/dp/{asin}")
    return urls


def scrape_bsr(asin, domain, retries=2):
    """Scrape BSR from an Amazon product page, trying multiple URL formats."""
    urls_to_try = build_urls(asin, domain)

    for attempt in range(retries + 1):
        try:
            if attempt > 0:
                wait = random.uniform(5, 12)
                logger.info(f"      Retry {attempt}/{retries}, waiting {wait:.1f}s...")
                time.sleep(wait)

            headers = get_random_headers()
            session = requests.Session()

            # Try each URL variant until we get BSR data
            last_error = 'BSR not found'
            for url in urls_to_try:
                response = session.get(url, headers=headers, timeout=20, allow_redirects=True)

                if response.status_code == 404:
                    logger.info(f"      Product {asin} not available on {domain}")
                    return {'success': False, 'error': 'Not available (404)'}
                elif response.status_code == 503:
                    logger.warning(f"      Bot blocked (503)")
                    last_error = 'Bot blocked (503)'
                    break
                elif response.status_code != 200:
                    last_error = f'HTTP {response.status_code}'
                    continue

                soup = BeautifulSoup(response.content, 'lxml')

                # Check CAPTCHA
                title_tag = soup.find('title')
                if title_tag and any(w in title_tag.text.lower() for w in ['robot', 'captcha', 'sorry']):
                    logger.warning(f"      Bot detection")
                    last_error = 'Bot detection'
                    break

                bsr_data = extract_bsr_from_html(soup)
                if bsr_data:
                    return {
                        'success': True,
                        'primary_rank': bsr_data[0]['rank'],
                        'primary_category': bsr_data[0]['category'],
                        'all_ranks': bsr_data,
                        'url': url
                    }
                # Try next URL variant
                logger.info(f"      No BSR at {url}, trying next variant...")
                time.sleep(2)

            if attempt < retries:
                continue
            logger.warning(f"      No BSR found for {asin} on {domain}")
            return {'success': False, 'error': last_error, 'url': urls_to_try[0]}

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
