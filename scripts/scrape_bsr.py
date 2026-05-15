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


def extract_bsr_from_html(soup):
    """Extract BSR data using multiple fallback strategies."""
    bsr_data = []

    # Strategy 1: Detail bullets wrapper (modern Amazon layout)
    detail_bullets = soup.find('div', {'id': 'detailBulletsWrapper_feature_div'})
    if detail_bullets:
        for li in detail_bullets.find_all('li'):
            text = li.get_text(separator=' ', strip=True)
            if any(kw in text for kw in ['Best Sellers Rank', 'Bestsellers Rank', 'Amazon Bestsellers Rank', 'Best Seller Rank']):
                ranks = re.findall(r'#([\d,]+)\s+in\s+([^\(#\n]+)', text)
                for rank_str, category in ranks:
                    bsr_data.append({
                        'rank': int(rank_str.replace(',', '')),
                        'category': category.strip().rstrip('(').strip()
                    })
                if bsr_data:
                    return bsr_data

    # Strategy 2: Product details table
    for table_id in ['productDetails_detailBullets_sections1', 'productDetails_techSpec_section_1']:
        table = soup.find('table', {'id': table_id})
        if table:
            for row in table.find_all('tr'):
                th = row.find('th')
                td = row.find('td')
                if th and td and 'Best Sellers Rank' in th.get_text():
                    text = td.get_text(separator=' ', strip=True)
                    ranks = re.findall(r'#([\d,]+)\s+in\s+([^\(#\n]+)', text)
                    for rank_str, category in ranks:
                        bsr_data.append({
                            'rank': int(rank_str.replace(',', '')),
                            'category': category.strip().rstrip('(').strip()
                        })
                    if bsr_data:
                        return bsr_data

    # Strategy 3: Scan all text spans
    for span in soup.find_all('span', string=re.compile(r'Best Sellers Rank', re.I)):
        parent = span.parent
        if parent:
            text = parent.get_text(separator=' ', strip=True)
            ranks = re.findall(r'#([\d,]+)\s+in\s+([^\(#\n]+)', text)
            for rank_str, category in ranks:
                bsr_data.append({
                    'rank': int(rank_str.replace(',', '')),
                    'category': category.strip().rstrip('(').strip()
                })
            if bsr_data:
                return bsr_data

    # Strategy 4: Full page text scan
    page_text = soup.get_text(separator=' ')
    bsr_match = re.search(r'Best Sellers? Rank[:\s]+#?([\d,]+)\s+in\s+([^\(#\n]{3,60})', page_text, re.I)
    if bsr_match:
        bsr_data.append({
            'rank': int(bsr_match.group(1).replace(',', '')),
            'category': bsr_match.group(2).strip()
        })

    return bsr_data


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
