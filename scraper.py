import os
import sys
import re
import json
import urllib.parse
import fnmatch
import mimetypes
import requests
from bs4 import BeautifulSoup

# Global session with custom headers
session = requests.Session()

# Configuration
seed_url = None
target_domain = None
allowed_asset_domains = []
output_dir = None
headers = {}

# Keep track of crawled pages and assets
crawled_pages = set()
downloaded_assets = {} # Map of absolute URL -> local path relative to root

# Common file extensions for assets (not pages)
ASSET_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico',
    'css', 'js',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'zip', 'tar', 'gz', 'tgz', 'dmg', 'exe',
    'mp4', 'mp3', 'webm', 'ogg', 'wav',
    'woff', 'woff2', 'ttf', 'eot', 'otf',
    'xml', 'txt', 'json'
}

def is_asset_url(url):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    if '.' in path.split('/')[-1]:
        ext = path.split('.')[-1]
        if ext in ASSET_EXTENSIONS:
            return True
    return False

def domain_matches(domain, patterns):
    for pattern in patterns:
        if fnmatch.fnmatch(domain, pattern):
            return True
    return False

def clean_url(url):
    """Remove fragments and rebuild URL."""
    parsed = urllib.parse.urlparse(url)
    # Rebuild without fragment
    return urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        ''
    ))

def url_to_local_path(url, is_page):
    """
    Map an absolute URL to a relative local path from the root.
    E.g. https://fan60.princeton.edu/about -> about/index.html
    E.g. https://www.princeton.edu/logo.svg -> _assets/www.princeton.edu/logo.svg
    """
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    path = urllib.parse.unquote(parsed.path).lstrip('/')
    
    # Strip dangerous characters from path
    path_parts = []
    for part in path.split('/'):
        if not part or part == '.' or part == '..':
            continue
        # Remove characters that are unsafe for filenames
        part = re.sub(r'[\\:*?"<>|]', '_', part)
        path_parts.append(part)
        
    clean_path = '/'.join(path_parts)
    
    # Determine domain directory
    if domain == target_domain:
        # Save directly under root
        local_dir = clean_path
    else:
        # Save under _assets/<domain>/
        local_dir = f"_assets/{domain}/{clean_path}" if clean_path else f"_assets/{domain}"

    # Handle query parameters (e.g. for dynamic pages or asset cache-busters)
    query_suffix = ""
    if parsed.query:
        # Keep query parameters for pages that might display different content (e.g. page=1)
        # But for assets, we strip cache-busters like itok or ver
        is_cache_buster = any(x in parsed.query.lower() for x in ['itok', 'ver', 'v=', 'delta', 'hash', 'revision'])
        if is_page or not is_cache_buster:
            safe_query = re.sub(r'[\\/:*?"<>|]', '_', parsed.query)
            query_suffix = f"_{safe_query}"
            
    if is_page:
        # It's an HTML page. Ensure it maps to an index.html file
        if not local_dir:
            return "index.html"
        
        # If it ends with .html or .htm, use it directly (with query suffix if any)
        if local_dir.lower().endswith('.html') or local_dir.lower().endswith('.htm'):
            if query_suffix:
                base, ext = os.path.splitext(local_dir)
                return f"{base}{query_suffix}{ext}"
            return local_dir
            
        # Otherwise, save as /path/index.html
        if query_suffix:
            return f"{local_dir}{query_suffix}/index.html"
        return f"{local_dir}/index.html"
    else:
        # It's an asset. Ensure it has its extension
        if not local_dir:
            local_dir = "index_asset"
            
        if query_suffix:
            base, ext = os.path.splitext(local_dir)
            if ext:
                return f"{base}{query_suffix}{ext}"
            else:
                return f"{local_dir}{query_suffix}"
        return local_dir

def download_asset(url):
    """Download an asset and return its local path relative to root."""
    url = clean_url(url)
    if url in downloaded_assets:
        return downloaded_assets[url]
        
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    
    # Check if domain is allowed for assets
    if not domain_matches(domain, allowed_asset_domains):
        print(f"[-] Skipping asset download (domain not allowed): {url}")
        return url
        
    local_rel_path = url_to_local_path(url, is_page=False)
    local_abs_path = os.path.join(output_dir, local_rel_path)
    
    # Download file
    print(f"[*] Downloading asset: {url} -> {local_rel_path}")
    try:
        os.makedirs(os.path.dirname(local_abs_path), exist_ok=True)
        
        # Stream download in chunks
        response = session.get(url, headers=headers, stream=True, timeout=20)
        if response.status_code == 200:
            # Prevent infinite recursion on circular dependencies (e.g. self-importing styles)
            downloaded_assets[url] = local_rel_path
            
            with open(local_abs_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # If it's a CSS file, parse it to find embedded resources (fonts, images)
            if local_rel_path.endswith('.css'):
                process_css_file(local_abs_path, url)
            elif local_rel_path.endswith('.js'):
                process_js_file(local_abs_path)
                
            return local_rel_path
        else:
            print(f"[!] Failed to download asset {url}: HTTP {response.status_code}")
            return url
    except Exception as e:
        print(f"[!] Error downloading asset {url}: {e}")
        return url

def process_js_file(js_abs_path):
    """Strip sourceMappingURL comments from JS files to prevent console 404 errors."""
    try:
        with open(js_abs_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        cleaned = re.sub(r'//#\s*sourceMappingURL\s*=\s*[^\s\n\r]+', '', content, flags=re.IGNORECASE)
        if len(cleaned) != len(content):
            with open(js_abs_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
    except Exception as e:
        print(f"[!] Error processing JS {js_abs_path}: {e}")

def process_css_file(css_abs_path, css_url):
    """Scan a CSS file for url(...) imports, download assets, and rewrite them relative to the CSS file."""
    try:
        with open(css_abs_path, 'r', encoding='utf-8', errors='ignore') as f:
            css_content = f.read()
            
        # Regex to find url(...) references
        urls = re.findall(r'url\s*\(\s*[\'"]?([^\'"\)]+)[\'"]?\s*\)', css_content)
        
        # Regex to find @import references (e.g. @import "style.css"; or @import '../fonts/roboto.css';)
        imports = re.findall(r'@import\s*[\'"]([^\'"]+)[\'"]', css_content)
        
        rewrites = {}
        for asset_url in urls + imports:
            # Skip data URIs or empty
            if not asset_url or asset_url.startswith('data:'):
                continue
                
            # Resolve to absolute URL relative to the CSS file's URL
            abs_asset_url = urllib.parse.urljoin(css_url, asset_url)
            
            # Download asset
            local_rel_path = download_asset(abs_asset_url)
            
            if local_rel_path != abs_asset_url:
                # Calculate relative path from CSS file to the asset
                css_rel_dir = os.path.dirname(os.path.relpath(css_abs_path, output_dir))
                rel_path_to_asset = os.path.relpath(local_rel_path, css_rel_dir)
                rewrites[asset_url] = urllib.parse.quote(rel_path_to_asset, safe='/')
                
        # Rewrite CSS content
        for orig, rep in rewrites.items():
            css_content = css_content.replace(orig, rep)
            
        # Strip sourceMappingURL comments from CSS to prevent console 404 errors
        css_content = re.sub(r'/\*#\s*sourceMappingURL\s*=\s*.*?\*/', '', css_content, flags=re.IGNORECASE)
            
        with open(css_abs_path, 'w', encoding='utf-8') as f:
            f.write(css_content)
            
    except Exception as e:
        print(f"[!] Error processing CSS {css_abs_path}: {e}")

def handle_pagination(soup, url, pager):
    """Find other pages listed in the pager, fetch their items, append them to the current page, and remove the pager."""
    print(f"[*] Found pagination on {url}. Merging paginated items...")
    
    # 1. Locate the container block of the pager
    block_container = pager.find_parent(class_="block-ps-event-speaker-list")
    if not block_container:
        block_container = pager.find_parent(class_="block")
        
    if not block_container:
        print("[!] Could not locate parent block for pager. Skipping merge.")
        return
        
    list_container = block_container.find(class_="content-list-items")
    if not list_container:
        print("[!] Could not locate content-list-items container. Skipping merge.")
        return

    # Find the index of this block among similar blocks on page 0 to fallback on
    classes = block_container.get('class', [])
    try:
        if classes:
            selector = "." + ".".join(classes)
            similar_blocks = soup.select(selector)
        else:
            similar_blocks = soup.find_all(class_="block-ps-event-speaker-list")
        block_index = similar_blocks.index(block_container)
    except Exception:
        block_index = 0

    # Get block title to find matching block on paginated pages
    block_title_el = block_container.find(class_="content-list-title")
    block_title = block_title_el.get_text().strip() if block_title_el else None
        
    # 2. Extract page links from the pager
    page_urls = []
    for a in pager.find_all('a'):
        href = a.get('href')
        if href:
            resolved_href = urllib.parse.urljoin(url, href)
            parsed = urllib.parse.urlparse(resolved_href)
            query_params = urllib.parse.parse_qs(parsed.query)
            if 'page' in query_params:
                page_num = query_params['page'][0]
                # Reconstruct a simplified URL to avoid Cloudflare pager_id block
                simplified_url = urllib.parse.urlunparse((
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    f"page={page_num}",
                    ''
                ))
                if simplified_url not in [item[1] for item in page_urls] and page_num != '0':
                    page_urls.append((int(page_num), simplified_url))
                    
    page_urls.sort()
    
    # 3. Fetch each page and extract items
    for page_num, page_url in page_urls:
        print(f"[*] Fetching paginated items from {page_url}...")
        try:
            res = session.get(page_url, headers=headers, timeout=15)
            if res.status_code == 200:
                sub_soup = BeautifulSoup(res.text, 'html.parser')
                
                # Find all potential matching blocks on the subpage
                if classes:
                    selector = "." + ".".join(classes)
                    all_blocks_sub = sub_soup.select(selector)
                else:
                    all_blocks_sub = sub_soup.find_all(class_="block-ps-event-speaker-list")
                
                sub_block = None
                # Try finding matching block by title first
                if block_title and all_blocks_sub:
                    for candidate in all_blocks_sub:
                        cand_title_el = candidate.find(class_="content-list-title")
                        cand_title = cand_title_el.get_text().strip() if cand_title_el else None
                        if cand_title == block_title:
                            sub_block = candidate
                            break
                            
                # Fall back to index matching if not found by title
                if not sub_block and all_blocks_sub and block_index < len(all_blocks_sub):
                    sub_block = all_blocks_sub[block_index]
                    
                if sub_block:
                    sub_list = sub_block.find(class_="content-list-items")
                    if sub_list:
                        items = sub_list.find_all(class_="content-list-item")
                        print(f"[*] Found {len(items)} items on page {page_num}. Merging...")
                        for item in items:
                            list_container.append(item)
                    else:
                        print(f"[!] Could not find list items on page {page_num}.")
                else:
                    print(f"[!] Could not find block container on page {page_num}.")
            else:
                print(f"[!] Failed to fetch page {page_num}: HTTP {res.status_code}")
        except Exception as e:
            print(f"[!] Error fetching/parsing page {page_num}: {e}")
            
    # 4. Remove the pager element so it doesn't render
    pager.decompose()
    print("[*] Successfully merged all pages and removed the pager navigation.")

def crawl_page(url):
    """Crawl an HTML page, save it, process assets, and find sub-links."""
    url = clean_url(url)
    if url in crawled_pages:
        return
        
    print(f"\n[+] Crawling page: {url}")
    crawled_pages.add(url)
    
    try:
        response = session.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"[!] Skip page {url} (HTTP {response.status_code})")
            return
            
        # Verify content type
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/html' not in content_type:
            print(f"[*] Page {url} is not HTML (Content-Type: {content_type}). Downloading as asset.")
            download_asset(url)
            return
            
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        # Handle participant pagination merging
        pager = soup.find('nav', class_='pager')
        if pager:
            handle_pagination(soup, url, pager)
            
        # Remove login link
        login_link = soup.find('a', class_='ps-login-link')
        if login_link:
            utility_menu = login_link.find_parent(class_='utility-menu')
            if utility_menu:
                utility_menu.decompose()
            else:
                parent_li = login_link.find_parent('li')
                if parent_li:
                    parent_li.decompose()
                else:
                    login_link.decompose()
        
        # Calculate current page directory relative to root
        local_rel_path = url_to_local_path(url, is_page=True)
        local_abs_path = os.path.join(output_dir, local_rel_path)
        current_page_rel_dir = os.path.dirname(local_rel_path)
        
        # Define a helper to rewrite a URL to a relative path
        def make_relative(target_url, is_target_page):
            resolved = urllib.parse.urljoin(url, target_url)
            resolved = clean_url(resolved)
            
            parsed_target = urllib.parse.urlparse(resolved)
            target_domain_name = parsed_target.netloc.lower()
            
            if is_target_page:
                if target_domain_name == target_domain:
                    # Resolve to local path
                    target_local_path = url_to_local_path(resolved, is_page=True)
                    rel_path = os.path.relpath(target_local_path, current_page_rel_dir)
                    return urllib.parse.quote(rel_path, safe='/')
                return target_url
            else:
                # It's an asset
                if domain_matches(target_domain_name, allowed_asset_domains):
                    target_local_path = download_asset(resolved)
                    if target_local_path != resolved:
                        rel_path = os.path.relpath(target_local_path, current_page_rel_dir)
                        return urllib.parse.quote(rel_path, safe='/')
                return target_url

        # 1. Process stylesheet/asset links (<link>)
        for link in soup.find_all('link'):
            rel = [r.lower() for r in link.get('rel', [])]
            href = link.get('href')
            if href:
                resolved_href = urllib.parse.urljoin(url, href)
                resolved_href = clean_url(resolved_href)
                
                is_css = 'stylesheet' in rel or resolved_href.lower().endswith('.css')
                is_icon = any('icon' in r for r in rel) or resolved_href.lower().endswith(('.ico', '.png', '.gif', '.svg'))
                
                if is_css or is_icon or is_asset_url(resolved_href):
                    new_href = make_relative(href, is_target_page=False)
                else:
                    new_href = make_relative(href, is_target_page=True)
                    
                if new_href != href:
                    link['href'] = new_href

        # 2. Process scripts (<script src="...">)
        for script in soup.find_all('script'):
            src = script.get('src')
            if src:
                if 'MathJax.js' in src or 'MathJax_config' in src:
                    # Redirect to CDN to avoid downloading and hosting massive MathJax library with dynamic plugin dependencies
                    script['src'] = "https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.9/MathJax.js?config=TeX-AMS-MML_HTMLorMML"
                else:
                    new_src = make_relative(src, is_target_page=False)
                    if new_src != src:
                        script['src'] = new_src

        # 3. Process images (<img src="..." srcset="...">)
        for img in soup.find_all(['img', 'source']):
            src = img.get('src')
            if src:
                new_src = make_relative(src, is_target_page=False)
                if new_src != src:
                    img['src'] = new_src
                    
            srcset = img.get('srcset')
            if srcset:
                new_parts = []
                for part in srcset.split(','):
                    part = part.strip()
                    if not part:
                        continue
                    tokens = part.split()
                    if tokens:
                        asset_url = tokens[0]
                        new_asset_url = make_relative(asset_url, is_target_page=False)
                        tokens[0] = new_asset_url
                        new_parts.append(' '.join(tokens))
                img['srcset'] = ', '.join(new_parts)

        # 4. Process internal links (<a href="...">) and queue them
        links_to_crawl = []
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href or href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:') or href.startswith('javascript:'):
                continue
                
            resolved_href = urllib.parse.urljoin(url, href)
            resolved_href = clean_url(resolved_href)
            
            parsed_href = urllib.parse.urlparse(resolved_href)
            href_domain = parsed_href.netloc.lower()
            
            # Check if this is an asset link or an HTML page link
            if is_asset_url(resolved_href):
                new_href = make_relative(href, is_target_page=False)
                if new_href != href:
                    a['href'] = new_href
            else:
                # It's a webpage
                if href_domain == target_domain:
                    # Queue for crawling if we haven't visited it yet
                    links_to_crawl.append(resolved_href)
                    new_href = make_relative(href, is_target_page=True)
                    a['href'] = new_href
                else:
                    # External webpage link - leave as is
                    pass

        # 5. Process elements with inline styles containing url(...)
        for el in soup.find_all(style=True):
            style = el.get('style')
            urls = re.findall(r'url\s*\(\s*[\'"]?([^\'"\)]+)[\'"]?\s*\)', style)
            for asset_url in urls:
                if asset_url.startswith('data:'):
                    continue
                new_url = make_relative(asset_url, is_target_page=False)
                if new_url != asset_url:
                    # Escape special regex characters in the original url
                    escaped_url = re.escape(asset_url)
                    style = re.sub(r'url\s*\(\s*[\'"]?' + escaped_url + r'[\'"]?\s*\)', f"url('{new_url}')", style)
            el['style'] = style

        # Write modified HTML page
        os.makedirs(os.path.dirname(local_abs_path), exist_ok=True)
        with open(local_abs_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
            
        # Now recursively crawl links
        for next_url in links_to_crawl:
            if next_url not in crawled_pages:
                crawl_page(next_url)
                
    except Exception as e:
        print(f"[!] Error crawling page {url}: {e}")

def main():
    global seed_url, target_domain, allowed_asset_domains, output_dir, headers
    
    if len(sys.argv) < 2:
        print("Usage: scraper.py <config.json>")
        sys.exit(1)
        
    config_path = sys.argv[1]
    with open(config_path, 'r') as f:
        config = json.load(f)
        
    seed_url = config.get('url')
    output_dir = config.get('output_dir')
    headers = config.get('headers', {})
    
    parsed_seed = urllib.parse.urlparse(seed_url)
    target_domain = parsed_seed.netloc.lower()
    
    # Configure asset domains - target domain is always allowed
    allowed_asset_domains = [target_domain]
    asset_domains_raw = config.get('allowed_asset_domains', '')
    if asset_domains_raw:
        domains = [d.strip().lower() for d in asset_domains_raw.split(',') if d.strip()]
        allowed_asset_domains.extend(domains)
        
    print("=== Crawler Started ===")
    print(f"Seed URL: {seed_url}")
    print(f"Target Domain: {target_domain}")
    print(f"Allowed Asset Domains: {allowed_asset_domains}")
    print(f"Output Directory: {output_dir}")
    print(f"Custom Headers: {list(headers.keys())}")
    print("=======================")
    
    # Set default user agent if not provided
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        
    crawl_page(seed_url)
    
    print("\n=== Crawl Completed ===")
    print(f"Total HTML pages crawled: {len(crawled_pages)}")
    print(f"Total assets downloaded: {len(downloaded_assets)}")
    
if __name__ == '__main__':
    main()
