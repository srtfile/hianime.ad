#!/usr/bin/env python3
"""
HiAnime URL Scraper - GitHub Actions Compatible
Extracts anime URLs from hianime.ad with automatic GitHub updates
"""

import requests
import json
import time
import sys
import re
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime
from pathlib import Path


class HiAnimeURLScraper:
    def __init__(self, output_dir="data"):
        self.base_url = "https://hianime.ad"
        self.list_url = f"{self.base_url}/az-list/all"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Setup session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        
        self.session.cookies.set('user_timezone', 'Asia/Dhaka')
        self.session.cookies.set('type_sub_name', 'dub')
        
        self.anime_data = []
        self.failed_pages = []
        self.seen_normalized_urls = {}
    
    def normalize_url(self, url):
        """
        Normalize URL by removing domain extension
        hianime.ad, hianime.org, hianime.net -> all treated as same
        """
        try:
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            path = re.sub(r'^(anime|watch)/', '', path)
            path = re.sub(r'/ep-\d+$', '', path)
            return path.lower()
        except:
            return url.lower()
    
    def parse_anime_item(self, item):
        """Parse a single anime item from HTML"""
        try:
            link_elem = item.find('a', class_='film-poster-ahref')
            if not link_elem:
                return None
            
            href = link_elem.get('href', '').strip()
            if not href or '/anime/' not in href:
                return None
            
            if any(skip in href for skip in ['/genres/', '/filter', '/home', '/login']):
                return None
            
            title_elem = item.find('a', class_='dynamic-name')
            title = title_elem.text.strip() if title_elem else None
            
            if not title:
                img_elem = item.find('img', class_='film-poster-img')
                if img_elem:
                    title = img_elem.get('alt', '').strip()
            
            if not title or len(title) < 2:
                return None
            
            img_elem = item.find('img', class_='film-poster-img')
            poster_url = img_elem.get('src', '') or img_elem.get('data-src', '') if img_elem else ''
            
            info_spans = item.find_all('span', class_='fdi-item')
            anime_type = info_spans[0].text.strip() if len(info_spans) >= 1 else None
            year = info_spans[1].text.strip() if len(info_spans) >= 2 else None
            
            tick_item = item.find('div', class_='tick-sub')
            episode_count = None
            if tick_item:
                numbers = ''.join(filter(str.isdigit, tick_item.get_text(strip=True)))
                if numbers:
                    episode_count = int(numbers)
            
            slug = href.replace('/anime/', '').rstrip('/')
            watch_url = f"/watch/{slug}/ep-1"
            full_url = self.base_url + watch_url
            
            normalized = self.normalize_url(full_url)
            
            if normalized in self.seen_normalized_urls:
                return None
            
            self.seen_normalized_urls[normalized] = full_url
            
            return {
                'title': title,
                'slug': slug,
                'url': full_url,
                'poster': poster_url,
                'type': anime_type,
                'year': year,
                'episodes': episode_count
            }
        
        except Exception:
            return None
    
    def parse_anime_page(self, html_content):
        """Parse HTML to extract anime data"""
        soup = BeautifulSoup(html_content, 'html.parser')
        anime_items_html = soup.find_all('div', class_='flw-item')
        
        if not anime_items_html:
            return []
        
        anime_items = []
        for item in anime_items_html:
            anime = self.parse_anime_item(item)
            if anime:
                anime_items.append(anime)
        
        return anime_items
    
    def scrape_page(self, page_num):
        """Scrape a single page"""
        url = f"{self.list_url}?page={page_num}"
        
        try:
            print(f"[{page_num:3d}/259] Fetching...", end=' ', flush=True)
            
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            anime_items = self.parse_anime_page(response.content)
            
            if anime_items:
                print(f"✓ {len(anime_items)} anime")
                return anime_items
            else:
                print("✗ No anime")
                return []
        
        except Exception as e:
            print(f"✗ Error: {str(e)[:30]}")
            self.failed_pages.append((page_num, str(e)))
            return []
    
    def scrape_all_pages(self, start_page=1, end_page=259, delay=0.5):
        """Scrape all pages"""
        print(f"\n{'='*70}")
        print(f"HiAnime URL Scraper - Pages {start_page} to {end_page}")
        print(f"{'='*70}\n")
        
        start_time = time.time()
        
        for page in range(start_page, end_page + 1):
            anime_items = self.scrape_page(page)
            self.anime_data.extend(anime_items)
            
            if page < end_page:
                time.sleep(delay)
        
        elapsed = time.time() - start_time
        
        print(f"\n{'='*70}")
        print(f"Total anime collected: {len(self.anime_data)}")
        print(f"Unique URLs: {len(self.seen_normalized_urls)}")
        print(f"Failed pages: {len(self.failed_pages)}")
        print(f"Time elapsed: {elapsed:.2f}s ({elapsed/60:.2f}m)")
        print(f"{'='*70}\n")
        
        return self.anime_data
    
    def save_to_json(self, filename="anime_urls.json"):
        """Save to JSON with serial IDs"""
        filepath = self.output_dir / filename
        
        # Add serial IDs
        output_data = []
        for idx, anime in enumerate(self.anime_data, start=1):
            anime_copy = {'id': idx}
            anime_copy.update(anime)
            output_data.append(anime_copy)
        
        # Create metadata
        metadata = {
            'last_updated': datetime.now().isoformat(),
            'total_anime': len(output_data),
            'source': 'hianime.ad',
            'scraper_version': '2.0'
        }
        
        # Final output
        final_output = {
            'metadata': metadata,
            'anime': output_data
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(final_output, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved {len(output_data)} unique anime to {filepath}")
        return filepath


def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description='HiAnime URL Scraper for GitHub Actions')
    parser.add_argument('--start', type=int, default=1, help='Start page')
    parser.add_argument('--end', type=int, default=259, help='End page')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between pages')
    parser.add_argument('--output', default='data', help='Output directory')
    
    args = parser.parse_args()
    
    scraper = HiAnimeURLScraper(output_dir=args.output)
    
    scraper.scrape_all_pages(
        start_page=args.start,
        end_page=args.end,
        delay=args.delay
    )
    
    scraper.save_to_json()
    
    print(f"✓ Done!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n✗ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)
