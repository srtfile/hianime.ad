#!/usr/bin/env python3
"""
HiAnime URL Scraper - Incremental Updates
Tracks progress and only scrapes new pages
"""

import requests
import json
import time
import sys
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path


class HiAnimeIncrementalScraper:
    def __init__(self, output_dir="data"):
        self.base_url = "https://hianime.ad"
        self.list_url = f"{self.base_url}/az-list/all"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # GitHub raw URL
        self.github_json_url = "https://raw.githubusercontent.com/srtfile/hianime.ad/refs/heads/main/data/anime_urls.json"
        
        # Files
        self.anime_json_file = self.output_dir / "anime_urls.json"
        self.track_file = self.output_dir / "hianimepagetrack.json"
        self.error_file = self.output_dir / "error.txt"
        
        # Setup session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        self.session.cookies.set('user_timezone', 'Asia/Dhaka')
        self.session.cookies.set('type_sub_name', 'dub')
        
        self.existing_anime = {}
        self.seen_normalized_urls = {}
        self.new_anime = []
        self.failed_pages = []
        self.last_scraped_page = 0
    
    def log_error(self, message):
        """Log errors to error.txt"""
        try:
            with open(self.error_file, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat()}] {message}\n")
        except:
            pass
    
    def normalize_url(self, url):
        """Normalize URL (ignore domain extension)"""
        try:
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            path = re.sub(r'^(anime|watch)/', '', path)
            path = re.sub(r'/ep-\d+$', '', path)
            return path.lower()
        except:
            return url.lower()
    
    def load_existing_data(self):
        """Load existing anime data from GitHub or local"""
        print("📥 Loading existing data...")
        
        # Try GitHub first
        try:
            print(f"   Fetching from GitHub...")
            response = self.session.get(self.github_json_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'anime' in data:
                    for anime in data['anime']:
                        normalized = self.normalize_url(anime['url'])
                        self.existing_anime[normalized] = anime
                        self.seen_normalized_urls[normalized] = anime['url']
                    print(f"   ✓ Loaded {len(self.existing_anime)} anime from GitHub")
                    return True
        except Exception as e:
            print(f"   ✗ GitHub failed: {e}")
            self.log_error(f"GitHub load error: {e}")
        
        # Try local
        try:
            if self.anime_json_file.exists():
                print(f"   Trying local file...")
                with open(self.anime_json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'anime' in data:
                        for anime in data['anime']:
                            normalized = self.normalize_url(anime['url'])
                            self.existing_anime[normalized] = anime
                            self.seen_normalized_urls[normalized] = anime['url']
                        print(f"   ✓ Loaded {len(self.existing_anime)} anime from local")
                        return True
        except Exception as e:
            print(f"   ✗ Local failed: {e}")
            self.log_error(f"Local load error: {e}")
        
        print("   ℹ Starting fresh")
        return False
    
    def load_track_file(self):
        """Load page tracking"""
        try:
            if self.track_file.exists():
                with open(self.track_file, 'r', encoding='utf-8') as f:
                    track = json.load(f)
                    self.last_scraped_page = track.get('last_page', 0)
                    print(f"📍 Last scraped page: {self.last_scraped_page}")
                    return
        except Exception as e:
            self.log_error(f"Track load error: {e}")
        
        self.last_scraped_page = 0
        print("📍 Starting from page 1")
    
    def save_track_file(self, last_page):
        """Save page tracking"""
        try:
            track = {
                'last_page': last_page,
                'last_updated': datetime.now().isoformat(),
                'total_anime': len(self.existing_anime) + len(self.new_anime)
            }
            with open(self.track_file, 'w', encoding='utf-8') as f:
                json.dump(track, f, indent=2)
        except Exception as e:
            self.log_error(f"Track save error: {e}")
    
    def parse_anime_item(self, item):
        """Parse single anime item"""
        try:
            link_elem = item.find('a', class_='film-poster-ahref')
            if not link_elem:
                return None
            
            href = link_elem.get('href', '').strip()
            if not href or '/anime/' not in href:
                return None
            
            title_elem = item.find('a', class_='dynamic-name')
            title = title_elem.text.strip() if title_elem else None
            if not title:
                img = item.find('img', class_='film-poster-img')
                title = img.get('alt', '').strip() if img else None
            if not title or len(title) < 2:
                return None
            
            img = item.find('img', class_='film-poster-img')
            poster = img.get('src', '') or img.get('data-src', '') if img else ''
            
            info = item.find_all('span', class_='fdi-item')
            anime_type = info[0].text.strip() if len(info) >= 1 else None
            year = info[1].text.strip() if len(info) >= 2 else None
            
            tick = item.find('div', class_='tick-sub')
            episodes = None
            if tick:
                nums = ''.join(filter(str.isdigit, tick.get_text(strip=True)))
                episodes = int(nums) if nums else None
            
            slug = href.replace('/anime/', '').rstrip('/')
            url = f"{self.base_url}/watch/{slug}/ep-1"
            
            normalized = self.normalize_url(url)
            if normalized in self.seen_normalized_urls:
                return None
            
            self.seen_normalized_urls[normalized] = url
            
            return {
                'title': title,
                'slug': slug,
                'url': url,
                'poster': poster,
                'type': anime_type,
                'year': year,
                'episodes': episodes
            }
        except Exception as e:
            self.log_error(f"Parse error: {e}")
            return None
    
    def scrape_page(self, page_num):
        """Scrape single page"""
        url = f"{self.list_url}?page={page_num}"
        
        try:
            print(f"[{page_num:3d}/259] ", end='', flush=True)
            
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            items = soup.find_all('div', class_='flw-item')
            
            if not items:
                print("✗ No items")
                return []
            
            anime_list = []
            for item in items:
                anime = self.parse_anime_item(item)
                if anime:
                    anime_list.append(anime)
            
            print(f"✓ {len(anime_list)} new")
            return anime_list
        
        except Exception as e:
            print(f"✗ Error")
            self.failed_pages.append((page_num, str(e)))
            self.log_error(f"Page {page_num} error: {e}")
            return []
    
    def scrape_incremental(self, start_page=None, end_page=259, delay=0.5):
        """Scrape pages incrementally"""
        print(f"\n{'='*70}")
        print(f"HiAnime Incremental Scraper")
        print(f"{'='*70}\n")
        
        self.load_existing_data()
        self.load_track_file()
        
        if start_page is None:
            start_page = self.last_scraped_page + 1
        
        print(f"\n📝 Scraping pages {start_page} to {end_page}\n")
        
        start_time = time.time()
        
        for page in range(start_page, end_page + 1):
            anime_list = self.scrape_page(page)
            self.new_anime.extend(anime_list)
            
            if page < end_page:
                time.sleep(delay)
        
        elapsed = time.time() - start_time
        
        print(f"\n{'='*70}")
        print(f"✓ Scraping Complete")
        print(f"{'='*70}")
        print(f"Existing anime: {len(self.existing_anime)}")
        print(f"New anime found: {len(self.new_anime)}")
        print(f"Failed pages: {len(self.failed_pages)}")
        print(f"Time: {elapsed:.2f}s ({elapsed/60:.2f}m)")
        print(f"{'='*70}\n")
        
        self.save_track_file(end_page)
        
        return self.new_anime
    
    def save_to_json(self, filename="anime_urls.json"):
        """Save merged data to JSON"""
        filepath = self.output_dir / filename
        
        # Merge existing + new
        all_anime = list(self.existing_anime.values()) + self.new_anime
        
        # Re-assign sequential IDs
        for idx, anime in enumerate(all_anime, start=1):
            anime['id'] = idx
        
        # Metadata
        metadata = {
            'last_updated': datetime.now().isoformat(),
            'total_anime': len(all_anime),
            'new_anime_this_run': len(self.new_anime),
            'source': 'hianime.ad',
            'scraper_version': '2.0-incremental'
        }
        
        output = {
            'metadata': metadata,
            'anime': all_anime
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved {len(all_anime)} anime ({len(self.new_anime)} new)")
        return filepath


def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description='HiAnime Incremental Scraper')
    parser.add_argument('--start', type=int, default=None, help='Start page (default: last+1)')
    parser.add_argument('--end', type=int, default=259, help='End page')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between pages')
    parser.add_argument('--output', default='data', help='Output directory')
    parser.add_argument('--full', action='store_true', help='Full scrape from page 1')
    
    args = parser.parse_args()
    
    scraper = HiAnimeIncrementalScraper(output_dir=args.output)
    
    start = 1 if args.full else args.start
    
    scraper.scrape_incremental(
        start_page=start,
        end_page=args.end,
        delay=args.delay
    )
    
    scraper.save_to_json()
    
    print("✅ Done!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n❌ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
