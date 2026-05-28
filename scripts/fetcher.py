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

# Short timeout for sitemap probes — these are just "does this path exist?"
# checks, so we don't want to wait the full TIMEOUT on each one.
SITEMAP_TIMEOUT = 4

# Hard cap on URLs we'll keep from a sitemap. Some big sites have 100k+ URLs;
# we don't need them all for SEO signal — first 10k tells us the structure.
MAX_SITEMAP_URLS = 10_000

# Common sitemap locations, ordered by real-world frequency.
# Most sites are caught by the first 3-4. The rest cover WordPress + edge cases.
COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",        # WordPress 5.5+ default
    "/sitemaps.xml",
    "/sitemap.xml.gz",        # gzipped — we decompress below
    "/post-sitemap.xml",      # Yoast splits by content type
    "/page-sitemap.xml",      # Yoast
    "/main-sitemap.xml",
    "/sitemap1.xml",
]


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

    # Defensive fallback: the loop above should always return, but if
    # MAX_RETRIES is ever set to 0 the loop body never runs. Returning a
    # well-shaped error dict keeps our "always returns a dict" promise.
    return {
        "html": "",
        "headers": {},
        "status_code": 0,
        "final_url": url,
        "error": "fetch_page: retry loop exited without result",
    }


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

    Strategy:
      1. Wait for `domcontentloaded` — fast, fires as soon as the HTML+JS
         parser finishes (no waiting on images, ads, analytics).
      2. THEN softly wait up to 5s for `networkidle` so JS-rendered content
         (React, Vue, etc.) has time to populate the DOM. We don't fail
         the whole fetch if networkidle never happens — many sites have
         long-running connections (websockets, analytics beacons) that
         keep them out of "idle" forever.
    """
    try:
        # Import inside the function so the module still loads
        # even if Playwright isn't installed yet.
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)

            # Fast initial load — fires when HTML+JS parsing is done.
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Soft wait for JS to settle. If it never reaches networkidle,
            # that's fine — we still get whatever content has rendered by 5s.
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # OK: some sites never go idle. Move on.

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


def _missing_title(html: str) -> bool:
    """True when a substantial HTML response has no populated <title> tag.

    Catches SPAs whose inline JSON bloats word count past the detect_spa()
    threshold (e.g. Next.js app-router pages, Chewy, Vercel-hosted React apps).
    We only trigger for responses >1 KB so we don't waste Playwright on 404s.
    """
    if not html or len(html) < 1000:
        return False
    return not re.search(r"<title[^>]*>\s*\S", html, re.IGNORECASE)


def smart_fetch(url: str) -> dict:
    """
    The function the agents actually call.

    Tries plain `requests` first (fast). Falls back to Playwright when either:
      - detect_spa() fires (SPA marker + low word count), OR
      - the response has substantial HTML but no <title> content (JS-rendered shell
        whose inline data fools the word-count check in detect_spa).

    The returned dict has an extra "fetch_method" key so we know which one ran.
    """
    result = fetch_page(url)

    html = result.get("html", "")
    status = result.get("status_code", 0)
    # Also try Playwright on non-200 status (429 rate-limit, 403 bot-block, etc.)
    # — a real browser fingerprint often gets through where requests doesn't.
    blocked = status not in (0, 200, 301, 302, 304)

    if detect_spa(html) or _missing_title(html) or blocked:
        playwright_result = fetch_with_playwright(url)
        # Only swap if Playwright actually got content
        if playwright_result.get("html"):
            result = playwright_result
        result["fetch_method"] = "playwright"
    else:
        result["fetch_method"] = "requests"

    return result


# ─────────────────────────────────────────────────────────────
# SUPPORTING FILE FETCHERS
# ─────────────────────────────────────────────────────────────

def _try_get(url: str, timeout: int = SITEMAP_TIMEOUT):
    """
    Single-shot GET that swallows network errors.

    Returns the requests.Response on HTTP 200 with non-empty body,
    None on any other outcome (404, timeout, DNS failure, etc.).

    Used for "probe" requests where we want to try a URL once and
    move on quickly if it doesn't exist.
    """
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if r.status_code == 200 and r.content:
            return r
    except requests.exceptions.RequestException:
        pass
    return None


def fetch_robots_txt(domain: str) -> dict:
    """
    Fetch and parse /robots.txt for a domain.

    Tries https://, then http://, with both www and non-www host variants.
    Captures ALL Sitemap: declarations — sites commonly declare several
    (e.g. post-sitemap, page-sitemap, product-sitemap in Yoast).

    Returns:
        {
            found:            True if any variant returned 200,
            disallowed_paths: list of paths from Disallow: lines,
            sitemap_urls:     list of all Sitemap: URLs found,
            sitemap_url:      first sitemap URL or None (kept for back-compat),
        }
    """
    flipped = domain[4:] if domain.startswith("www.") else "www." + domain
    candidates = [
        f"https://{domain}/robots.txt",
        f"https://{flipped}/robots.txt",
        f"http://{domain}/robots.txt",
        f"http://{flipped}/robots.txt",
    ]

    for url in candidates:
        r = _try_get(url, timeout=TIMEOUT)
        if r is None:
            continue

        disallowed = []
        sitemap_urls = []
        for line in r.text.splitlines():
            line = line.strip()
            if line.lower().startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    disallowed.append(path)
            elif line.lower().startswith("sitemap:"):
                sm = line.split(":", 1)[1].strip()
                if sm:
                    sitemap_urls.append(sm)

        return {
            "found": True,
            "disallowed_paths": disallowed,
            "sitemap_urls": sitemap_urls,
            "sitemap_url": sitemap_urls[0] if sitemap_urls else None,
        }

    return {
        "found": False,
        "disallowed_paths": [],
        "sitemap_urls": [],
        "sitemap_url": None,
    }


def _decode_sitemap_body(content: bytes) -> bytes:
    """
    Strip BOM and decompress gzip if needed.

    Returns bytes ready for ET.fromstring(). Idempotent — safe to call
    on already-clean content.
    """
    # gzip magic bytes: 0x1f 0x8b. If present, decompress.
    if content[:2] == b"\x1f\x8b":
        import gzip
        try:
            content = gzip.decompress(content)
        except Exception:
            pass  # Fall through with original bytes; parser will fail loudly

    # UTF-8 BOM: 0xef 0xbb 0xbf. Strip if present — ElementTree hates it.
    if content[:3] == b"\xef\xbb\xbf":
        content = content[3:]

    return content


def _parse_sitemap_xml(content: bytes) -> dict:
    """
    Parse a sitemap or sitemap index XML body.

    Handles regular sitemaps (<urlset><url><loc>) and sitemap index files
    (<sitemapindex><sitemap><loc>). Decompresses gzip and strips BOM
    automatically via _decode_sitemap_body.
    """
    content = _decode_sitemap_body(content)

    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"urls": [], "sub_sitemaps": []}

    urls = [el.text for el in root.findall("sm:url/sm:loc", namespace) if el.text]
    sub_sitemaps = [el.text for el in root.findall("sm:sitemap/sm:loc", namespace) if el.text]
    return {"urls": urls, "sub_sitemaps": sub_sitemaps}


def fetch_sitemap(
    domain: str,
    sitemap_url: str | None = None,
    sitemap_urls: list | None = None,
) -> dict:
    """
    Find and parse the site's sitemap(s).

    Discovery order (each tier short-circuits as soon as one URL responds):
      1. Explicit URLs declared in robots.txt (sitemap_urls — preferred)
      2. Legacy single hint (sitemap_url — kept for back-compat)
      3. Common candidate paths at the given domain over HTTPS

    Handles sitemap indexes (follows sub-sitemaps one level deep),
    gzip-compressed sitemaps, and UTF-8 BOMs.

    Returns:
        {
            found:              True if any candidate parsed successfully,
            page_count:         total URLs found across all sub-sitemaps,
            url_list:           deduplicated list, capped at MAX_SITEMAP_URLS,
            content_categories: top-level path segments (e.g. "blog", "products"),
            source_url:         which candidate URL actually worked,
        }
    """
    # Build candidate list in priority order, deduplicated as we go
    candidates: list[str] = []
    seen_candidates: set[str] = set()

    def _add(url):
        if url and url not in seen_candidates:
            seen_candidates.add(url)
            candidates.append(url)

    for u in sitemap_urls or []:
        _add(u)
    _add(sitemap_url)
    for path in COMMON_SITEMAP_PATHS:
        _add(f"https://{domain}{path}")

    # Walk candidates; stop at first one that looks like real XML (or gzip)
    raw_content = None
    source_url = None
    for url in candidates:
        r = _try_get(url)
        if r is None:
            continue
        head = r.content[:20].lower()
        is_xml = b"<?xml" in head or b"<urlset" in head or b"<sitemapindex" in head
        is_gzip = r.content[:2] == b"\x1f\x8b"
        if is_xml or is_gzip:
            raw_content = r.content
            source_url = url
            break

    if not raw_content:
        return {
            "found": False,
            "page_count": 0,
            "url_list": [],
            "content_categories": [],
            "source_url": None,
        }

    parsed = _parse_sitemap_xml(raw_content)
    all_urls = list(parsed["urls"])

    # Follow sub-sitemap links one level deep (sitemap index pattern)
    for sub_url in parsed["sub_sitemaps"]:
        if len(all_urls) >= MAX_SITEMAP_URLS:
            break
        r = _try_get(sub_url)
        if r is None:
            continue
        sub = _parse_sitemap_xml(r.content)
        all_urls.extend(sub["urls"])

    # Deduplicate while preserving discovery order
    seen_urls: set[str] = set()
    deduped = []
    for u in all_urls:
        if u not in seen_urls:
            seen_urls.add(u)
            deduped.append(u)
    deduped = deduped[:MAX_SITEMAP_URLS]

    categories = set()
    for u in deduped:
        parts = urlparse(u).path.strip("/").split("/")
        if parts and parts[0]:
            categories.add(parts[0])

    return {
        "found": True,
        "page_count": len(deduped),
        "url_list": deduped,
        "content_categories": sorted(categories),
        "source_url": source_url,
    }


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