#!/usr/bin/env python3
"""
Amazon BSR (Best Seller Rank) Scraper for KDP Dashboard
Scrapes BSR data from Amazon product pages for 17 countries.
Run daily via GitHub Actions.
"""

try:
    from curl_cffi import requests
    CURL_CFFI = True
except ImportError:
    import requests
    CURL_CFFI = False

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
if CURL_CFFI:
    logger.info("curl_cffi available — using Chrome TLS impersonation")
else:
    logger.warning("curl_cffi not available — falling back to plain requests (may be blocked)")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

# Chrome versions to rotate through for realistic impersonation
CHROME_VERSIONS = ['chrome119', 'chrome120', 'chrome124', 'chrome131']

# Minimal locale headers — curl_cffi sets UA + TLS automatically
LOCALE_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
}

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


def make_session():
    """Create a session with Chrome impersonation if curl_cffi is available."""
    if CURL_CFFI:
        version = random.choice(CHROME_VERSIONS)
        return requests.Session(impersonate=version)
    return requests.Session()


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
    clean = re.sub(
        r'\([^)]{0,120}(?:See|Voir|Vedi|Ver|Siehe|Conhe[çc]a|Consulta|Top\s+100)[^)]*\)',
        ' ', text, flags=re.IGNORECASE
    )
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
        if re.search(r'(?:See|Voir|Top\s+\d+|^\d+$)', cat, re.I):
            return
        key = (rank, cat.lower()[:40])
        if key not in seen:
            seen.add(key)
            results.append({'rank': rank, 'category': cat})

    for m in re.finditer(
        r'#\s*([\d,]+)\s+(?:in|em)\s+'
        r'([\wÀ-ɏ&\'’/()\-–, ]{3,80}?)'
        r'(?=\s*(?:#\s*\d|\d{1,3}\s+(?:in|em)\s+[A-ZÀ]|\Z|\n))',
        clean, re.UNICODE
    ):
        try: add(normalize_rank_number(m.group(1)), m.group(2))
        except: pass

    for m in re.finditer(
        r'(?<!\d)([\d][\d,\.]*) \s+(?:in|em)\s+'
        r'([A-ZÀ-ɏ][A-Za-zÀ-ɏ0-9&\'’/()\-, ]{2,70}?)'
        r'(?=\s*(?:Nr\.|[Nn][°º]|n\.)| \s{2,}|\s*(?:\d{1,6}\s+(?:in|em)\s+[A-ZÀ])|\Z|\n)',
        clean, re.UNICODE
    ):
        try:
            rank = normalize_rank_number(m.group(1))
            add(rank, m.group(2))
        except: pass

    if results:
        return results

    for m in re.finditer(
        r'(?:Nr\.|[Nn][°º]|n\.)\s*([\d.,\s]{1,15})\s+(?:in|en|em)\s+'
        r'([\wÀ-ɏ&\'’/()\-, ]{3,80}?)'
        r'(?=\s*(?:Nr\.|[Nn][°º]|n\.|$|\n|\())',
        clean, re.UNICODE
    ):
        try:
            rank = normalize_rank_number(m.group(1).strip())
            add(rank, m.group(2))
        except: pass

    return results


BSR_KEYWORDS = [
    'Best Sellers Rank', 'Bestsellers Rank', 'Amazon Best Sellers Rank',
    'Amazon Bestseller-Rang', 'Bestseller-Rang', 'Bestseller-Rang:',
    'Meilleures ventes', 'Classement des meilleures ventes',
    'Posizione nella classifica', 'Classifica Bestseller', 'classifica Bestseller',
    'Posición en los más vendidos', 'Los más vendidos', 'más vendidos',
    'Ranking dos mais vendidos', 'Mais vendidos', 'mais vendidos',
    'Más vendidos', 'más vendidos',
    'ランキング', '売れ筋ランキング', 'Amazon売れ筋ランキング',
    'Bestseller-rang', 'Bestsellerrang', 'Bästsäljare', 'Bestsellery',
    'Bestseller Rang', 'Ranking',
]


def has_bsr_keyword(text):
    return any(kw.lower() in text.lower() for kw in BSR_KEYWORDS)


def extract_bsr_from_html(soup):
    """Extract ALL BSR rank entries using multiple fallback strategies, all locales."""
    bsr_data = []
    page_text = soup.get_text(separator=' ')

    def parse_from_page(keyword_hint):
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

    detail_bullets = soup.find('div', {'id': 'detailBulletsWrapper_feature_div'})
    if detail_bullets:
        for li in detail_bullets.find_all('li'):
            text = li.get_text(separator=' ', strip=True)
            if has_bsr_keyword(text):
                matched_kw = next((kw for kw in BSR_KEYWORDS if kw.lower() in text.lower()), None)
                bsr_data = parse_from_page(matched_kw)
                if bsr_data:
                    return bsr_data

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

    for tag in soup.find_all(['span', 'li']):
        text = tag.get_text(separator=' ', strip=True)
        if has_bsr_keyword(text) and len(text) < 2000:
            matched_kw = next((kw for kw in BSR_KEYWORDS if kw.lower() in text.lower()), None)
            bsr_data = parse_from_page(matched_kw)
            if bsr_data:
                return bsr_data

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
    clean = re.sub(r'\([^)]{0,100}\)', ' ', block)
    results = []
    seen = set()
    pat = re.compile(
        r'\b([\d][\d,\.]*) \s+in\s+([A-Z][A-Za-z0-9 &/()\'’\-]{2,55}?)(?=\s{2,}|\s*\d|\Z|Customer|$)',
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


TITLE_SLUGS = {
    'B0GV2SS77G': {
        'www.amazon.co.uk': 'Claude-Finance-Professionals-Institutional-Investment',
        'www.amazon.es':    'Claude-Finance-Professionals-Institutional-Investment',
    },
    'B0GVJPXVP8': {
        'www.amazon.co.uk': 'Claude-Finance-Professionals-Institutional-Investment',
        'www.amazon.es':    'Claude-Finance-Professionals-Institutional-Investment',
    },
    '9357823662': {
        'www.amazon.co.uk': 'AI-Prompts-Financial-Analysis-Practical',
        'www.amazon.es':    'AI-Prompts-Financial-Analysis-Practical',
    },
    'B0GWWG34W6': {
        'www.amazon.co.uk': 'Wealth-Code-Chhatrapati-Shivaji-Maharaj',
        'www.amazon.es':    'Wealth-Code-Chhatrapati-Shivaji-Maharaj',
    },
    'B0GWHZLVK8': {
        'www.amazon.co.uk': 'Stop-Losing-Money-Stories-Private',
        'www.amazon.es':    'Stop-Losing-Money-Stories-Private',
    },
    'B0GSBV7QX9': {
        'www.amazon.co.uk': 'AI-Prompts-Financial-Analysis-Practical',
        'www.amazon.es':    'AI-Prompts-Financial-Analysis-Practical',
    },
}


def build_urls(asin, domain):
    urls = []
    slug = TITLE_SLUGS.get(asin, {}).get(domain)
    if slug:
        urls.append(f"https://{domain}/{slug}/dp/{asin}/ref=tmm_pap_swatch_0")
        urls.append(f"https://{domain}/{slug}/dp/{asin}")
    urls.append(f"https://{domain}/dp/{asin}")
    return urls


CI_MODE = os.environ.get('CI', '').lower() in ('true', '1', 'yes')


def scrape_bsr(asin, domain, retries=None):
    """Scrape BSR from an Amazon product page, trying multiple URL formats."""
    if retries is None:
        retries = 1 if CI_MODE else 2
    urls_to_try = build_urls(asin, domain)
    session = make_session()

    for url in urls_to_try:
        for attempt in range(retries + 1):
            try:
                if attempt > 0:
                    wait = random.uniform(2, 5) if CI_MODE else random.uniform(5, 12)
                    logger.info(f"      Retry {attempt}/{retries}, waiting {wait:.1f}s...")
                    time.sleep(wait)

                response = session.get(url, headers=LOCALE_HEADERS, timeout=20, allow_redirects=True)

                if response.status_code == 404:
                    logger.info(f"      Not available on {domain} (404)")
                    return {'success': False, 'error': 'Not available (404)'}

                if response.status_code in (503, 429):
                    logger.warning(f"      Rate limited ({response.status_code})")
                    return {'success': False, 'error': f'Rate limited ({response.status_code})'}

                if response.status_code != 200:
                    if attempt < retries:
                        continue
                    return {'success': False, 'error': f'HTTP {response.status_code}'}

                soup = BeautifulSoup(response.content, 'lxml')

                title_tag = soup.find('title')
                page_len = len(response.content)
                if page_len < 1000 or (title_tag and any(
                    w in title_tag.text.lower() for w in ['robot check', 'captcha', 'something went wrong', 'verify yourself']
                )):
                    logger.warning(f"      Bot detection (page {page_len}b)")
                    return {'success': False, 'error': 'Bot detection'}

                bsr_data = extract_bsr_from_html(soup)
                if bsr_data:
                    return {
                        'success': True,
                        'primary_rank': bsr_data[0]['rank'],
                        'primary_category': bsr_data[0]['category'],
                        'all_ranks': bsr_data,
                        'url': url
                    }

                logger.info(f"      No BSR at {url}")
                break

            except Exception as e:
                err = str(e).lower()
                if 'timeout' in err or 'timed out' in err:
                    if attempt < retries:
                        continue
                    logger.warning(f"      Timeout: {url}")
                    break
                if attempt < retries:
                    continue
                logger.error(f"      Error: {e}")
                break

        time.sleep(random.uniform(1, 2))

    logger.warning(f"      No BSR found for {asin} on {domain}")
    return {'success': False, 'error': 'BSR not found', 'url': urls_to_try[0]}


def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def git_commit_rankings(filepath, message):
    """In CI, commit and push after each book so progress is preserved on timeout."""
    if not CI_MODE:
        return
    import subprocess
    try:
        subprocess.run(['git', 'add', filepath], check=True, capture_output=True)
        result = subprocess.run(['git', 'diff', '--staged', '--quiet'], capture_output=True)
        if result.returncode != 0:
            subprocess.run(['git', 'commit', '-m', message], check=True, capture_output=True)
            subprocess.run(['git', 'push'], check=True, capture_output=True)
            logger.info(f"  [git commit+push: {message}]")
        else:
            logger.info(f"  [No changes to commit]")
    except Exception as e:
        logger.warning(f"  [git commit failed: {e}]")


TOP_LEVEL_CATS = {
    'kindle store', 'books', 'livros', 'libros', 'bücher', 'livres',
    'libri', 'kindle storeの商品', 'kindle ストア',
}


def update_audit_log(rankings, books_data, date_key):
    """
    Personal-bests board: per book, per format, track the best rank EVER
    achieved in each sub-category. Updated daily — a record is only changed
    when today's rank beats the stored best.

    Structure:
      audit_log[book_id][fmt_name] = {
        cat_key: {best_rank, category, country, date}
      }
    """
    rankings.setdefault('audit_log', {})

    for book in books_data['books']:
        book_id = book['id']
        rankings['audit_log'].setdefault(book_id, {})

        for fmt_name, countries in rankings['current'].get(book_id, {}).items():
            rankings['audit_log'][book_id].setdefault(fmt_name, {})
            bests = rankings['audit_log'][book_id][fmt_name]

            for country, data in countries.items():
                if not isinstance(data, dict):
                    continue
                for item in data.get('all_ranks', []):
                    rank = item.get('rank')
                    cat = (item.get('category') or '').strip()
                    if not rank or not cat or cat.lower() in TOP_LEVEL_CATS:
                        continue
                    key = cat.lower()[:60]
                    if key not in bests or rank < bests[key]['best_rank']:
                        bests[key] = {
                            'best_rank': rank,
                            'category': cat,
                            'country': country,
                            'date': date_key,
                        }

                # Fallback to primary rank when all_ranks is absent
                if not data.get('all_ranks') and data.get('rank') and data.get('category'):
                    cat = data['category'].strip()
                    if cat.lower() not in TOP_LEVEL_CATS:
                        key = cat.lower()[:60]
                        rank = data['rank']
                        if key not in bests or rank < bests[key]['best_rank']:
                            bests[key] = {
                                'best_rank': rank,
                                'category': cat,
                                'country': country,
                                'date': date_key,
                            }

    logger.info("  [audit_log updated]")


def update_rankings():
    """Main update loop — scrapes all books x formats x countries."""
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
                    hist = rankings['history'][book_id][fmt_name].setdefault(country_code, [])
                    hist.append({'date': date_key, 'rank': result['primary_rank'], 'category': result['primary_category']})
                    rankings['history'][book_id][fmt_name][country_code] = hist[-90:]
                    logger.info(f"    OK: #{result['primary_rank']:,} in {result['primary_category']}")
                    success_count += 1
                else:
                    logger.warning(f"    FAIL: {result['error']}")
                    fail_count += 1
                    existing = rankings['current'][book_id][fmt_name].get(country_code, {})
                    existing['last_error'] = result['error']
                    existing['error_timestamp'] = timestamp
                    rankings['current'][book_id][fmt_name][country_code] = existing

                time.sleep(random.uniform(2, 4) if CI_MODE else random.uniform(3, 7))

        rankings_path = os.path.join(DATA_DIR, 'rankings.json')
        save_json(rankings_path, rankings)
        git_commit_rankings(
            rankings_path,
            f"chore: update BSR rankings {date_key} — {book['title'][:40]}"
        )

    update_audit_log(rankings, books_data, date_key)
    rankings_path = os.path.join(DATA_DIR, 'rankings.json')
    save_json(rankings_path, rankings)
    git_commit_rankings(rankings_path, f"chore: update BSR audit log {date_key}")

    logger.info(f"\nDone! Success: {success_count}, Failed: {fail_count}")
    return rankings


if __name__ == '__main__':
    update_rankings()
