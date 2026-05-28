"""
Parsers Module
==============

Pure HTML extraction functions. Given a BeautifulSoup object (or raw HTML),
each function pulls out one specific signal and returns it as a dict or value.

Organized into sections that match the TODO:
  1. Meta signals       (title, description, canonical, OG, Twitter, viewport)
  2. Content structure  (headings, word count, FAQ, author, dates)
  3. Schema             (JSON-LD blocks, LocalBusiness check)
  4. Links              (internal/external counts, anchor text quality)
  5. Trust & conversion (contact info, social proof, CTA)
  6. Tech fingerprinting (CMS, framework, analytics, marketing tools)
  7. Readability        (Flesch-Kincaid grade level)

None of these functions fetch anything — they only parse. Pair them with
fetcher.py to get a full pipeline.
"""

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


# ─────────────────────────────────────────────────────────────
# CONVENIENCE HELPER
# ─────────────────────────────────────────────────────────────

def make_soup(html: str) -> BeautifulSoup:
    """Turn raw HTML into a BeautifulSoup object. Use 'lxml' parser for speed."""
    return BeautifulSoup(html or "", "lxml")


# ═════════════════════════════════════════════════════════════
# 1. META SIGNALS
# ═════════════════════════════════════════════════════════════

def parse_title(soup: BeautifulSoup) -> dict:
    """<title> tag — text, length, and optimal-length check (50-60 chars)."""
    tag = soup.find("title")
    if not tag or not tag.string:
        return {"text": None, "length": 0, "optimal_length": False}
    text = tag.string.strip()
    return {
        "text": text,
        "length": len(text),
        "optimal_length": 50 <= len(text) <= 60,
    }


def parse_meta_description(soup: BeautifulSoup) -> dict:
    """<meta name="description"> — text, length, optimal-length check (150-160)."""
    tag = soup.find("meta", attrs={"name": "description"})
    if not tag or not tag.get("content"):
        return {"text": None, "length": 0, "optimal_length": False}
    text = tag["content"].strip()
    return {
        "text": text,
        "length": len(text),
        "optimal_length": 150 <= len(text) <= 160,
    }


def parse_canonical(soup: BeautifulSoup):
    """<link rel="canonical"> — returns the URL or None."""
    tag = soup.find("link", rel="canonical")
    return tag["href"] if tag and tag.get("href") else None


def parse_open_graph(soup: BeautifulSoup) -> dict:
    """All <meta property="og:..."> tags as a dict."""
    og = {}
    for tag in soup.find_all("meta", attrs={"property": True}):
        prop = tag.get("property", "")
        if prop.startswith("og:"):
            og[prop] = tag.get("content", "")
    return og


def parse_twitter_card(soup: BeautifulSoup) -> dict:
    """<meta name="twitter:card"> — present? what type?"""
    tag = soup.find("meta", attrs={"name": "twitter:card"})
    if not tag:
        return {"present": False, "card_type": None}
    return {"present": True, "card_type": tag.get("content")}


def parse_viewport(soup: BeautifulSoup) -> dict:
    """<meta name="viewport"> — present and mobile-friendly?"""
    tag = soup.find("meta", attrs={"name": "viewport"})
    if not tag:
        return {"present": False, "mobile_friendly": False, "content": None}
    content = tag.get("content", "")
    return {
        "present": True,
        "content": content,
        # The standard mobile-friendly viewport includes width=device-width
        "mobile_friendly": "width=device-width" in content,
    }


# ═════════════════════════════════════════════════════════════
# 2. CONTENT STRUCTURE
# ═════════════════════════════════════════════════════════════

def _clean_heading(tag) -> str:
    """Extract clean text from a heading tag.

    separator=' ' adds a space between child elements so adjacent inline spans
    don't run together (e.g. 'product' + 'development' → 'product development').
    After that, collapse whitespace and strip repeated phrases — some JS frameworks
    embed 2–3 responsive variants of the same heading inside one <h1>/<h2>.
    """
    text = re.sub(r'\s+', ' ', tag.get_text(separator=' ')).strip()
    words = text.split()
    n = len(words)
    for divisor in [3, 2]:
        if n >= divisor * 4 and n % divisor == 0:
            chunk = n // divisor
            if all(words[i * chunk:(i + 1) * chunk] == words[:chunk]
                   for i in range(1, divisor)):
                return ' '.join(words[:chunk])
    return text


def parse_headings(soup: BeautifulSoup) -> dict:
    """H1/H2/H3 lists with counts."""
    result = {}
    for level in ["h1", "h2", "h3"]:
        tags = soup.find_all(level)
        result[level] = {
            "count": len(tags),
            "texts": [_clean_heading(t) for t in tags],
        }
    return result


def check_h1(headings: dict) -> dict:
    """SEO best practice: exactly one H1 per page."""
    h1 = headings.get("h1", {})
    count = h1.get("count", 0)
    return {
        "exists": count > 0,
        "exactly_one": count == 1,
        "count": count,
        "texts": h1.get("texts", []),
    }


def estimate_word_count(soup: BeautifulSoup) -> int:
    """
    Approximate visible body word count.

    We work on a copy of the soup so we can strip out scripts, styles, nav,
    footer, and header without mutating the original. What's left is roughly
    the actual article/content text.
    """
    # Re-parse to make a clean copy we can mutate
    soup_copy = BeautifulSoup(str(soup), "lxml")
    for tag_name in ["script", "style", "nav", "footer", "header", "noscript"]:
        for tag in soup_copy.find_all(tag_name):
            tag.decompose()
    text = soup_copy.get_text(separator=" ", strip=True)
    return len(text.split())


def find_faq_section(soup: BeautifulSoup) -> bool:
    """Does this page have an FAQ section? (Signal for FAQ rich-snippet opportunity.)"""
    # Check headings for "FAQ" or "frequently asked"
    for heading in soup.find_all(["h1", "h2", "h3"]):
        heading_text = heading.get_text().lower()
        if "faq" in heading_text or "frequently asked" in heading_text:
            return True
    # Also catch FAQPage schema as a strong signal
    if "faqpage" in str(soup).lower():
        return True
    return False


def parse_author_info(soup: BeautifulSoup) -> dict:
    """Try several common patterns to find the author's name."""
    author = None

    # Pattern 1: <meta name="author">
    meta_tag = soup.find("meta", attrs={"name": "author"})
    if meta_tag and meta_tag.get("content"):
        author = meta_tag["content"].strip()

    # Pattern 2: <a rel="author">
    if not author:
        a_tag = soup.find("a", rel="author")
        if a_tag:
            author = a_tag.get_text(strip=True)

    # Pattern 3: any element with class="author" (or "post-author", etc.)
    if not author:
        author_elem = soup.find(attrs={"class": re.compile(r"\bauthor\b", re.I)})
        if author_elem:
            text = author_elem.get_text(strip=True)
            # Cap the length so we don't grab a whole bio paragraph
            author = text[:100] if text else None

    return {"name": author, "found": author is not None}


def parse_dates(soup: BeautifulSoup) -> dict:
    """Published date and last-modified date, if available."""
    published = None
    modified = None

    pub_meta = soup.find("meta", attrs={"property": "article:published_time"})
    if pub_meta:
        published = pub_meta.get("content")

    mod_meta = soup.find("meta", attrs={"property": "article:modified_time"})
    if mod_meta:
        modified = mod_meta.get("content")

    # Fallback: first <time datetime="..."> tag
    if not published:
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            published = time_tag["datetime"]

    return {"published": published, "modified": modified}


# ═════════════════════════════════════════════════════════════
# 3. SCHEMA / STRUCTURED DATA
# ═════════════════════════════════════════════════════════════

def parse_schema(soup: BeautifulSoup) -> dict:
    """
    Find all <script type="application/ld+json"> blocks and parse them.

    Returns the full schemas (for deeper inspection) and a flat list of
    @type values (for quick "do they have LocalBusiness schema?" checks).
    """
    schemas = []
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        # A JSON-LD block can be a list OR a single object — handle both
        if isinstance(data, list):
            schemas.extend([item for item in data if isinstance(item, dict)])
        elif isinstance(data, dict):
            schemas.append(data)

    # Pull out just the @type values into a flat list
    types_found = []
    for schema in schemas:
        type_val = schema.get("@type")
        if isinstance(type_val, list):
            types_found.extend(type_val)
        elif isinstance(type_val, str):
            types_found.append(type_val)

    return {"schemas": schemas, "types_found": types_found}


def check_local_business_schema(schema_result: dict) -> dict:
    """For local SEO: does LocalBusiness schema exist, and is it complete?"""
    # All these are "subtypes" of LocalBusiness in schema.org
    local_types = {
        "LocalBusiness", "Restaurant", "Store", "Dentist", "Plumber",
        "HVACBusiness", "LegalService", "HomeAndConstructionBusiness",
        "FinancialService", "MedicalBusiness", "ProfessionalService",
    }

    has_local = has_geo = has_hours = False

    for schema in schema_result.get("schemas", []):
        type_val = schema.get("@type", "")
        type_list = type_val if isinstance(type_val, list) else [type_val]

        if any(t in local_types for t in type_list):
            has_local = True
            if "geo" in schema:
                has_geo = True
            if "openingHours" in schema or "openingHoursSpecification" in schema:
                has_hours = True

    return {
        "present": has_local,
        "has_geo": has_geo,
        "has_opening_hours": has_hours,
    }


# ═════════════════════════════════════════════════════════════
# 4. LINKS
# ═════════════════════════════════════════════════════════════

def parse_links(soup: BeautifulSoup, base_url: str) -> dict:
    """Count internal vs external links and collect anchor text."""
    base_domain = urlparse(base_url).netloc
    internal, external, anchors = [], [], []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        anchor_text = a.get_text(strip=True)
        if anchor_text:
            anchors.append(anchor_text)

        # Skip non-link hrefs
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue

        # Resolve relative URLs against the base
        absolute = urljoin(base_url, href)
        link_domain = urlparse(absolute).netloc

        if link_domain == base_domain or not link_domain:
            internal.append(absolute)
        else:
            external.append(absolute)

    return {
        "internal_count": len(internal),
        "external_count": len(external),
        "internal": internal,
        "external": external,
        "anchor_texts": anchors,
    }


def flag_bad_anchor_text(anchors: list) -> list:
    """Generic anchor text hurts SEO — flag instances of 'click here', etc."""
    bad_phrases = {"click here", "read more", "here", "this", "link", "more", "learn more"}
    return [text for text in anchors if text.lower().strip() in bad_phrases]


# ═════════════════════════════════════════════════════════════
# 5. TRUST & CONVERSION
# ═════════════════════════════════════════════════════════════

def parse_trust_signals(soup: BeautifulSoup) -> dict:
    """Indicators that a real, trustworthy business is behind this page."""
    text = soup.get_text().lower()
    html = str(soup).lower()

    # Common trust pages
    has_contact = bool(soup.find("a", href=re.compile(r"contact", re.I)))
    has_about = bool(soup.find("a", href=re.compile(r"about", re.I)))
    has_privacy = bool(soup.find("a", href=re.compile(r"privacy", re.I)))

    # Visible contact info — simple US phone pattern (e.g. 555-123-4567)
    has_phone = bool(re.search(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", text))
    has_email = bool(re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", text))

    # Social proof indicators in the copy
    social_proof_words = ["testimonial", "review", "rated", "trusted by", "client"]
    has_social_proof = any(word in text for word in social_proof_words)

    # Links to social media platforms
    platforms = ["facebook.com", "instagram.com", "linkedin.com",
                 "twitter.com", "x.com", "youtube.com", "tiktok.com"]
    social_links = [p for p in platforms if p in html]

    return {
        "contact_link": has_contact,
        "about_link": has_about,
        "privacy_link": has_privacy,
        "phone_visible": has_phone,
        "email_visible": has_email,
        "has_social_proof": has_social_proof,
        "social_platforms_linked": social_links,
    }


def parse_cta(soup: BeautifulSoup) -> dict:
    """Find the primary call-to-action button or link."""
    # Strategy 1: look for elements with btn/button/cta in their class name
    cta_class_pattern = re.compile(r"btn|button|cta", re.I)
    for elem in soup.find_all(["button", "a"], class_=cta_class_pattern):
        text = elem.get_text(strip=True)
        if text and len(text) < 50:
            return {"text": text, "tag": elem.name, "found": True}

    # Strategy 2: scan links for CTA-style phrases
    cta_phrases = ["get started", "sign up", "contact us", "book now", "schedule",
                   "buy now", "shop now", "request a quote", "free quote", "call now"]
    for link in soup.find_all("a"):
        text = link.get_text(strip=True).lower()
        if any(phrase in text for phrase in cta_phrases) and len(text) < 50:
            return {"text": link.get_text(strip=True), "tag": "a", "found": True}

    return {"text": None, "tag": None, "found": False}


# ═════════════════════════════════════════════════════════════
# 6. TECH FINGERPRINTING
# These take raw HTML (a string), not a soup object — they're string matchers.
# ═════════════════════════════════════════════════════════════

def detect_cms(html: str) -> str:
    """Identify the content management system from telltale strings."""
    h = html.lower()
    if "wp-content" in h or "wp-includes" in h:
        return "WordPress"
    if "cdn.shopify.com" in h:
        return "Shopify"
    if "static.squarespace.com" in h:
        return "Squarespace"
    if "wixstatic" in h or "wix.com" in h:
        return "Wix"
    if "webflow" in h:
        return "Webflow"
    return "Unknown"


def detect_framework(html: str):
    """Identify the JS framework, if any."""
    h = html.lower()
    if "__next_data__" in h or "_next/static" in html:
        return "Next.js"
    if "__nuxt" in h:
        return "Nuxt.js"
    if "ng-version" in html or "ng-app" in html:
        return "Angular"
    if "data-v-" in html or "v-cloak" in html:
        return "Vue"
    # Check React LAST since Next/Nuxt would also match
    if "data-reactroot" in html or "react" in h:
        return "React"
    return None


def detect_analytics(html: str) -> list:
    """List all analytics tools detected on the page."""
    found = []
    h = html.lower()
    if "googletagmanager.com" in h or "gtm.js" in h:
        found.append("Google Tag Manager")
    if "google-analytics.com" in h or "gtag(" in html or "ga.js" in h:
        found.append("Google Analytics")
    if "hotjar" in h:
        found.append("Hotjar")
    if "cdn.segment.com" in h:
        found.append("Segment")
    if "mixpanel" in h:
        found.append("Mixpanel")
    if "fullstory" in h:
        found.append("FullStory")
    if "clarity.ms" in h:
        found.append("Microsoft Clarity")
    return found


def detect_marketing_tools(html: str) -> list:
    """List all marketing/CRM/chat tools detected."""
    found = []
    h = html.lower()
    if "hs-analytics" in h or "hubspot" in h:
        found.append("HubSpot")
    if "intercom" in h:
        found.append("Intercom")
    if "driftt.com" in h or "drift.com" in h:
        found.append("Drift")
    if "klaviyo" in h:
        found.append("Klaviyo")
    if "mailchimp" in h or "list-manage.com" in h:
        found.append("Mailchimp")
    if "calendly" in h:
        found.append("Calendly")
    if "typeform" in h:
        found.append("Typeform")
    return found


# ═════════════════════════════════════════════════════════════
# 7. READABILITY
# ═════════════════════════════════════════════════════════════

def score_readability(text: str) -> dict:
    """
    Flesch-Kincaid grade level → audience.

    Roughly:
      grade  < 9  → general consumer
      9–11        → educated
      12+         → specialist
    """
    try:
        import textstat
    except ImportError:
        return {"grade_level": None, "audience": None, "error": "textstat not installed"}

    if not text or len(text.split()) < 50:
        # Too little text to score reliably
        return {"grade_level": None, "audience": None}

    grade = textstat.flesch_kincaid_grade(text)

    if grade < 9:
        audience = "general consumer"
    elif grade < 12:
        audience = "educated"
    else:
        audience = "specialist"

    return {"grade_level": round(grade, 1), "audience": audience}


# ─────────────────────────────────────────────────────────────
# QUICK TEST
# Uses an inline HTML sample so we don't need network access.
# Run with:  python scripts/parsers.py
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    SAMPLE_HTML = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>Joe's Plumbing — Fort Lauderdale's Trusted Plumber</title>
        <meta name="description" content="Joe's Plumbing has served Fort Lauderdale for 20 years. Fast, reliable service for emergencies, repairs, and installations. Call us today!">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="canonical" href="https://joesplumbing.com/">
        <meta property="og:title" content="Joe's Plumbing">
        <meta property="og:image" content="https://joesplumbing.com/og.jpg">
        <meta name="twitter:card" content="summary_large_image">
        <script type="application/ld+json">
          {"@type": "Plumber", "name": "Joe's Plumbing",
           "geo": {"latitude": 26.12, "longitude": -80.14},
           "openingHours": "Mo-Fr 08:00-18:00"}
        </script>
      </head>
      <body>
        <header><nav><a href="/about">About</a> <a href="/contact">Contact</a></nav></header>
        <main>
          <h1>Fort Lauderdale Plumbing Services</h1>
          <h2>Emergency Repairs</h2>
          <p>We've been serving Fort Lauderdale since 2004 with same-day service. Call 954-555-1234.</p>
          <h2>Frequently Asked Questions</h2>
          <a href="/quote" class="btn-primary">Get a Free Quote</a>
          <a href="https://facebook.com/joesplumbing">Facebook</a>
        </main>
        <footer><a href="/privacy">Privacy Policy</a></footer>
      </body>
    </html>
    """

    soup = make_soup(SAMPLE_HTML)
    base_url = "https://joesplumbing.com/"

    print("── META ──")
    print(f"  title:        {parse_title(soup)}")
    print(f"  description:  {parse_meta_description(soup)}")
    print(f"  canonical:    {parse_canonical(soup)}")
    print(f"  viewport:     {parse_viewport(soup)}")

    print("\n── CONTENT ──")
    headings = parse_headings(soup)
    print(f"  headings:     {headings}")
    print(f"  h1 check:     {check_h1(headings)}")
    print(f"  word count:   {estimate_word_count(soup)}")
    print(f"  FAQ section:  {find_faq_section(soup)}")

    print("\n── SCHEMA ──")
    schema = parse_schema(soup)
    print(f"  types found:  {schema['types_found']}")
    print(f"  local biz:    {check_local_business_schema(schema)}")

    print("\n── LINKS ──")
    links = parse_links(soup, base_url)
    print(f"  internal: {links['internal_count']}, external: {links['external_count']}")

    print("\n── TRUST & CTA ──")
    print(f"  trust:        {parse_trust_signals(soup)}")
    print(f"  CTA:          {parse_cta(soup)}")

    print("\n── TECH ──")
    print(f"  CMS:          {detect_cms(SAMPLE_HTML)}")
    print(f"  framework:    {detect_framework(SAMPLE_HTML)}")
    print(f"  analytics:    {detect_analytics(SAMPLE_HTML)}")