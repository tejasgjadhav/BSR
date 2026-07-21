#!/usr/bin/env python3
"""
Amazon BSR (Best Seller Rank) Scraper for KDP Dashboard
Scrapes BSR data from Amazon product pages for 17 countries.
Run daily via local launchd (Amazon blocks datacenter/CI IPs; a real
headless Chrome from a residential IP gets through).
"""

from playwright.sync_api import sync_playwright

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
logger.info("Using headless Chrome (Playwright) with bot-interstitial handling")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

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


_PW = None
_BROWSER = None
_CONTEXT = None

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _get_context():
    """Lazily launch one headless Chrome + context, reused for the whole run."""
    global _PW, _BROWSER, _CONTEXT
    if _CONTEXT is not None:
        return _CONTEXT
    _PW = sync_playwright().start()
    launch_args = dict(headless=True, args=['--disable-blink-features=AutomationControlled'])
    try:
        _BROWSER = _PW.chromium.launch(channel='chrome', **launch_args)
    except Exception:
        # Fall back to Playwright's bundled Chromium if system Chrome is absent.
        _BROWSER = _PW.chromium.launch(**launch_args)
    _CONTEXT = _BROWSER.new_context(
        user_agent=USER_AGENT, locale='en-US', viewport={'width': 1280, 'height': 900}
    )
    _CONTEXT.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};"
    )
    return _CONTEXT


def close_browser():
    global _PW, _BROWSER, _CONTEXT
    try:
        if _BROWSER:
            _BROWSER.close()
        if _PW:
            _PW.stop()
    except Exception:
        pass
    _PW = _BROWSER = _CONTEXT = None


def fetch_html(url):
    """Load an Amazon page with headless Chrome, clicking through the
    'Continue shopping' bot-interstitial when it appears. Returns (status, html)."""
    page = _get_context().new_page()
    try:
        resp = page.goto(url, timeout=30000, wait_until='domcontentloaded')
        status = resp.status if resp else 0
        page.wait_for_timeout(800)
        body = page.inner_text('body')
        if 'continue shopping' in body.lower() and 'Best Sellers Rank' not in body:
            try:
                btn = page.get_by_role('button', name=re.compile('continue shopping', re.I))
                if not btn.count():
                    btn = page.locator("button:has-text('Continue shopping'), input[type=submit]")
                btn.first.click(timeout=5000)
                page.wait_for_load_state('domcontentloaded', timeout=15000)
                page.wait_for_timeout(800)
                status = 200
            except Exception:
                pass
        return status, page.content()
    finally:
        page.close()


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
    # Truncate at the field that follows the BSR list so the LAST rank entry
    # isn't swallowed by trailing text. Case-insensitive — Amazon renders
    # "Customer Reviews" (capital R), which a case-sensitive find would miss.
    for stop in ['avalia', 'customer review', 'recensioni', 'reseñas',
                 'kundrezensionen', 'rezensionen', 'avis client', 'opiniones',
                 'date first available', 'asin', 'publisher', 'publication date']:
        idx = clean.lower().find(stop)
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

    for url in urls_to_try:
        for attempt in range(retries + 1):
            try:
                if attempt > 0:
                    wait = random.uniform(2, 5) if CI_MODE else random.uniform(5, 12)
                    logger.info(f"      Retry {attempt}/{retries}, waiting {wait:.1f}s...")
                    time.sleep(wait)

                status_code, html = fetch_html(url)

                if status_code == 404:
                    logger.info(f"      Not available on {domain} (404)")
                    return {'success': False, 'error': 'Not available (404)'}

                if status_code in (503, 429):
                    logger.warning(f"      Rate limited ({status_code})")
                    return {'success': False, 'error': f'Rate limited ({status_code})'}

                if status_code and status_code != 200:
                    if attempt < retries:
                        continue
                    return {'success': False, 'error': f'HTTP {status_code}'}

                soup = BeautifulSoup(html, 'lxml')

                title_tag = soup.find('title')
                page_len = len(html)
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

    logger.info(f"\nDone! Success: {success_count}, Failed: {fail_count}")
    return rankings


if __name__ == '__main__':
    try:
        update_rankings()
    finally:
        close_browser()
