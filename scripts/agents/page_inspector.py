"""
Page Inspector Agent (fully wired version)
"""

from urllib.parse import urlparse

from scripts.fetcher import (
    smart_fetch, fetch_robots_txt, fetch_sitemap, fetch_subpage,
)
from scripts.parsers import (
    make_soup,
    parse_title, parse_meta_description, parse_canonical,
    parse_open_graph, parse_twitter_card, parse_viewport,
    parse_headings, estimate_word_count, find_faq_section,
    parse_author_info, parse_dates, score_readability,
    parse_schema, check_local_business_schema,
    parse_links, flag_bad_anchor_text,
    parse_trust_signals, parse_cta,
    detect_cms, detect_framework, detect_analytics, detect_marketing_tools,
)
from scripts.pagespeed import get_pagespeed


def run(url: str, depth: str = "surface") -> dict:
    domain = urlparse(url).netloc

    page = smart_fetch(url)
    html = page["html"]
    soup = make_soup(html)

    robots = fetch_robots_txt(domain)

    sitemap = None
    if depth == "deep":
        sitemap = fetch_sitemap(domain, sitemap_urls=robots.get("sitemap_urls"))
        for path in ["/about", "/contact", "/services", "/reviews"]:
            fetch_subpage(domain, path)  # fetched but not stored on the report yet

    headings = parse_headings(soup)
    schema = parse_schema(soup)
    link_data = parse_links(soup, url)

    meta = {
        "title": parse_title(soup),
        "description": parse_meta_description(soup),
        "canonical": parse_canonical(soup),
        "open_graph": parse_open_graph(soup),
        "twitter_card": parse_twitter_card(soup),
        "viewport": parse_viewport(soup),
    }

    body_text = soup.get_text(separator=" ", strip=True)[:5000]

    content = {
        "headings": headings,
        "word_count": estimate_word_count(soup),
        "faq_present": find_faq_section(soup),
        "author": parse_author_info(soup),
        "dates": parse_dates(soup),
        "readability_grade": score_readability(body_text),
        "body_snippet": body_text[:3000],
    }

    local_check = check_local_business_schema(schema)
    schema_summary = {
        "types_found": schema["types_found"],
        "local_business_present": local_check["present"],
        "local_business_has_geo": local_check["has_geo"],
    }

    trust_data = parse_trust_signals(soup)
    trust = {
        "https": url.startswith("https://"),
        "contact_link": trust_data["contact_link"],
        "about_link": trust_data["about_link"],
        "privacy_link": trust_data["privacy_link"],
        "phone_visible": trust_data["phone_visible"],
        "email_visible": trust_data["email_visible"],
        "has_social_proof": trust_data["has_social_proof"],
        "social_platforms_linked": trust_data["social_platforms_linked"],
        "primary_cta": parse_cta(soup),
    }

    links = {
        "internal_count": link_data["internal_count"],
        "external_count": link_data["external_count"],
        "external": link_data["external"],
        "bad_anchors": flag_bad_anchor_text(link_data["anchor_texts"]),
    }

    tech = {
        "cms": detect_cms(html),
        "framework": detect_framework(html),
        "analytics": detect_analytics(html),
        "marketing_tools": detect_marketing_tools(html),
    }

    pagespeed = get_pagespeed(url)
    security = {"headers_score": 0, "headers_present": [], "ssl_expiry_days": None}

    site_structure = {
        "robots_disallowed_paths": robots["disallowed_paths"],
        "sitemap_page_count": sitemap["page_count"] if sitemap else 0,
        "content_categories": sitemap["content_categories"] if sitemap else [],
    }

    return {
        "url": url,
        "domain": domain,
        "fetch_method": page.get("fetch_method", "requests"),
        "meta": meta,
        "content": content,
        "schema": schema_summary,
        "links": links,
        "trust": trust,
        "tech": tech,
        "pagespeed": pagespeed,
        "security": security,
        "site_structure": site_structure,
    }