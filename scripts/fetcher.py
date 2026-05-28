"""
Fetcher Module
==============

Handles all HTTP fetching for the Website Analyzer:
  - regular pages (with retries + timeout)
  - SPA detection (does this page need a browser to render?)
  - Playwright fallback for JS-rendered pages
  - robots.txt and sitemap.xml parsing
  - subpage fetching (/about, /contact, etc.)

Every function returns a dict and never raises an uncaught exception —
that way the agents calling us can always inspect the result safely.
"""

import re
import time
import requests
from urllib.parse import urlparse
from xml.etree import ElementTree as ET


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

TIMEOUT = 10                # seconds before we give up on a request
MAX_RETRIES = 3             # how many times to retry a failed fetch
RETRY_DELAY = 1             # seconds to wait between retries
USER_AGENT = "Mozilla/5.0 (compatible; WebsiteAnalyzer/1.0)"


# ─────────────────────────────────────────────────────────────
# CORE FETCH FUNCTIONS
# ─────────────────────────────────────────────────────────────

def fetch_page(url: str) -> dict:
    """
    Fetch a single URL using the `requests` library.

    Retries up to 3 times on network errors. Always returns a dict —
    if everything fails, the dict will have status_code=0 and an error message.
    """
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=TIMEOUT,
                allow_redirects=True,   # follow 301/302 redirects automatically
            )
            return {
                "html": response.text,
                "headers": dict(response.headers),
                "status_code": response.status_code,
                "final_url": response.url,   # where we ended up after redirects
                "error": None,
            }
        except requests.exceptions.RequestException as e:
            # Last attempt? Give up and return an error dict.
            if attempt == MAX_RETRIES - 1:
                return {
                    "html": "",
                    "headers": {},
                    "status_code": 0,
                    "final_url": url,
                    "error": str(e),
                }
            # Otherwise wait a moment and try again.
            time.sleep(RETRY_DELAY)


def detect_spa(html: str) -> bool:
    """
    Check if a page looks like a JavaScript Single-Page App (SPA).

    SPAs render their content with JS in the browser, so when we fetch them
    with `requests` we get a near-empty HTML shell. We need Playwright for those.

    Returns True only when we see BOTH:
      1. A common SPA marker in the HTML
      2. Very little visible text (under 100 words)

    Both signals together avoid false positives on sites that use React
    but still server-render their content (like Next.js with SSR).
    """
    if not html:
        return False

    # Common framework fingerprints
    spa_markers = [
        "__NEXT_DATA__",     # Next.js (though this often means SSR is happening)
        'id="root"',         # default React mount point
        "ng-version",        # Angular
        "data-reactroot",    # older React
    ]
    has_spa_marker = any(marker in html for marker in spa_markers)

    # Rough word count of visible text: strip HTML tags, collapse whitespace
    text_only = re.sub(r"<[^>]+>", " ", html)
    text_only = re.sub(r"\s+", " ", text_only).strip()
    word_count = len(text_only.split())

    return has_spa_marker and word_count < 100


def fetch_with_playwright(url: str) -> dict:
    """
    Render a page in a real headless browser using Playwright.

    Slower than `fetch_page` but necessary for JS-heavy sites.
    Requires `playwright install chromium` to have been run once.
    """
    try:
        # Import inside the function so the module still loads
        # even if Playwright isn't installed yet.
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            response = page.goto(url, wait_until="networkidle", timeout=30000)
            html = page.content()
            final_url = page.url
            status = response.status if response else 0
            headers = dict(response.headers) if response else {}
            browser.close()

        return {
            "html": html,
            "headers": headers,
            "status_code": status,
            "final_url": final_url,
            "error": None,
        }
    except Exception as e:
        return {
            "html": "",
            "headers": {},
            "status_code": 0,
            "final_url": url,
            "error": f"Playwright error: {e}",
        }


def smart_fetch(url: str) -> dict:
    """
    The function the agents actually call.

    Tries plain `requests` first (fast). If that returns an SPA shell,
    falls back to Playwright (slower but real browser).

    The returned dict has an extra "fetch_method" key so we know which one ran.
    """
    result = fetch_page(url)

    if detect_spa(result["html"]):
        result = fetch_with_playwright(url)
        result["fetch_method"] = "playwright"
    else:
        result["fetch_method"] = "requests"

    return result


# ─────────────────────────────────────────────────────────────
# SUPPORTING FILE FETCHERS
# ─────────────────────────────────────────────────────────────

def fetch_robots_txt(domain: str) -> dict:
    """
    Fetch and parse /robots.txt for a domain.

    Returns the list of disallowed paths and any sitemap URL declared inside.
    If the file doesn't exist, returns found=False — the SEO Auditor can
    flag that as an issue.
    """
    url = f"https://{domain}/robots.txt"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        if response.status_code != 200:
            return {"found": False, "disallowed_paths": [], "sitemap_url": None}

        disallowed = []
        sitemap_url = None
        for line in response.text.splitlines():
            line = line.strip()
            # robots.txt lines look like:  Disallow: /admin   or   Sitemap: https://...
            if line.lower().startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    disallowed.append(path)
            elif line.lower().startswith("sitemap:"):
                sitemap_url = line.split(":", 1)[1].strip()

        return {
            "found": True,
            "disallowed_paths": disallowed,
            "sitemap_url": sitemap_url,
        }
    except requests.exceptions.RequestException:
        return {"found": False, "disallowed_paths": [], "sitemap_url": None}


def fetch_sitemap(domain: str, sitemap_url: str = None) -> dict:
    """
    Fetch and parse sitemap.xml.

    If a sitemap_url isn't passed in, we guess /sitemap.xml.
    We also infer rough "content categories" from the URL paths
    (e.g. /blog/, /services/, /products/) — useful for site-structure analysis.
    """
    if sitemap_url is None:
        sitemap_url = f"https://{domain}/sitemap.xml"

    try:
        response = requests.get(sitemap_url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        if response.status_code != 200:
            return {"found": False, "page_count": 0, "url_list": [], "content_categories": []}

        # Sitemap XML uses a namespace — we have to tell ElementTree about it.
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ET.fromstring(response.content)

        urls = [el.text for el in root.findall("sm:url/sm:loc", namespace) if el.text]

        # Top-level path segment becomes the "category" (e.g. /blog/post-1 → blog)
        categories = set()
        for u in urls:
            parts = urlparse(u).path.strip("/").split("/")
            if parts and parts[0]:
                categories.add(parts[0])

        return {
            "found": True,
            "page_count": len(urls),
            "url_list": urls,
            "content_categories": sorted(categories),
        }
    except (requests.exceptions.RequestException, ET.ParseError):
        return {"found": False, "page_count": 0, "url_list": [], "content_categories": []}


def fetch_subpage(domain: str, path: str) -> dict:
    """
    Fetch a known subpage like /about or /contact.

    Returns found=True if the page returned HTTP 200, found=False otherwise.
    """
    url = f"https://{domain}{path}"
    result = fetch_page(url)
    return {
        "found": result["status_code"] == 200,
        "html": result["html"],
        "url": result["final_url"],
    }


# ─────────────────────────────────────────────────────────────
# QUICK TEST
# Run this file directly with:  python scripts/fetcher.py
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_url = "https://example.com"
    print(f"Testing smart_fetch on {test_url}...")
    page = smart_fetch(test_url)
    print(f"  fetch_method: {page['fetch_method']}")
    print(f"  status_code:  {page['status_code']}")
    print(f"  final_url:    {page['final_url']}")
    print(f"  html length:  {len(page['html'])} chars")

    domain = urlparse(test_url).netloc
    print(f"\nTesting fetch_robots_txt on {domain}...")
    robots = fetch_robots_txt(domain)
    print(f"  found: {robots['found']}")
    print(f"  disallowed: {robots['disallowed_paths']}")

    print(f"\nTesting fetch_sitemap on {domain}...")
    sitemap = fetch_sitemap(domain)
    print(f"  found: {sitemap['found']}")
    print(f"  page_count: {sitemap['page_count']}")