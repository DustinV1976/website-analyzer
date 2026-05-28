"""
SEO Auditor Agent
=================

Takes the PAGE_INSPECTOR_REPORT from Agent 1 and turns its raw signals
into scored audit results:

  - E-E-A-T scores (4 pillars, 0-10 each)
  - Core Web Vitals verdicts (Good / Needs Improvement / Poor)
  - Local SEO checklist (only runs when site IS a local business)
  - Technical SEO checklist (critical / important / nice-to-have)
  - Inferred primary and secondary keywords
  - Content Quality Score (/100, weighted across 5 categories)
  - Sorted list of issues with plain-English fix recommendations

Usage:
    from agents.seo_auditor import run
    audit = run(page_inspector_report)
"""


# ═════════════════════════════════════════════════════════════
# 1. E-E-A-T SCORING (0-10 each pillar)
# ═════════════════════════════════════════════════════════════

def score_experience(report: dict) -> int:
    score = 0
    content = report.get("content", {})
    wc = content.get("word_count", 0)
    if wc >= 500: score += 3
    elif wc >= 300: score += 2
    elif wc >= 100: score += 1
    dates = content.get("dates", {})
    if dates.get("published"): score += 2
    if dates.get("modified"): score += 1
    if content.get("faq_present"): score += 1
    h2_count = content.get("headings", {}).get("h2", {}).get("count", 0)
    if h2_count >= 3: score += 2
    elif h2_count >= 1: score += 1
    if content.get("author", {}).get("found"): score += 1
    return min(score, 10)


def score_expertise(report: dict) -> int:
    score = 0
    content = report.get("content", {})
    schema = report.get("schema", {})
    links = report.get("links", {})
    if content.get("author", {}).get("found"): score += 4
    if content.get("word_count", 0) >= 500: score += 2
    types = schema.get("types_found", [])
    if any(t in ["Person", "Author", "Article", "BlogPosting"] for t in types):
        score += 2
    if links.get("external_count", 0) > 0: score += 2
    return min(score, 10)


def score_authoritativeness(report: dict) -> int:
    score = 0
    trust = report.get("trust", {})
    schema = report.get("schema", {})
    meta = report.get("meta", {})
    links = report.get("links", {})
    if trust.get("https"): score += 2
    if links.get("external_count", 0) > 0: score += 2
    if "Organization" in schema.get("types_found", []): score += 2
    if meta.get("open_graph"): score += 2
    if trust.get("social_platforms_linked"): score += 2
    return min(score, 10)


def score_trustworthiness(report: dict) -> int:
    score = 0
    trust = report.get("trust", {})
    security = report.get("security", {})
    if trust.get("https"): score += 3
    if trust.get("contact_link"): score += 2
    if trust.get("privacy_link"): score += 2
    if trust.get("phone_visible") or trust.get("email_visible"): score += 2
    ssl_days = security.get("ssl_expiry_days")
    if ssl_days is not None and ssl_days > 30: score += 1
    return min(score, 10)


def score_eeat(report: dict) -> dict:
    e = score_experience(report)
    ex = score_expertise(report)
    a = score_authoritativeness(report)
    t = score_trustworthiness(report)
    return {
        "experience": e, "expertise": ex,
        "authoritativeness": a, "trustworthiness": t,
        "total": e + ex + a + t,
    }


# ═════════════════════════════════════════════════════════════
# 2. CORE WEB VITALS
# ═════════════════════════════════════════════════════════════

def _verdict(value, good_max, poor_min):
    if value is None: return "Unknown"
    if value < good_max: return "Good"
    if value < poor_min: return "Needs Improvement"
    return "Poor"


CWV_RECOMMENDATIONS = {
    "lcp": {
        "Needs Improvement": "LCP is slow. Optimize the hero image, preload key fonts, and minimize render-blocking CSS.",
        "Poor": "LCP is very slow. Compress/lazy-load images, defer non-critical JS, and reduce render-blocking resources.",
    },
    "cls": {
        "Needs Improvement": "Layout is shifting. Set width/height on images and reserve space for ads/embeds.",
        "Poor": "Severe layout shift. Audit dynamic content insertions and add explicit dimensions to all media.",
    },
    "inp": {
        "Needs Improvement": "Interactivity is sluggish. Break up long JS tasks and reduce main-thread work.",
        "Poor": "Page feels broken on interaction. Audit heavy frameworks and third-party scripts.",
    },
}


def evaluate_core_web_vitals(report: dict) -> dict:
    ps = report.get("pagespeed", {})
    thresholds = {
        "lcp": (2.5, 4.0),
        "cls": (0.1, 0.25),
        "inp": (200, 500),
    }
    results = {}
    for metric, (good_max, poor_min) in thresholds.items():
        value = ps.get(metric)
        verdict = _verdict(value, good_max, poor_min)
        results[metric] = {
            "value": value,
            "verdict": verdict,
            "recommendation": CWV_RECOMMENDATIONS.get(metric, {}).get(verdict),
        }
    return results


# ═════════════════════════════════════════════════════════════
# 3. LOCAL SEO CHECKS
# Only meaningful for local-business sites. The synthesizer decides
# whether to surface these based on the detected business model.
# No location is hardcoded here — checks are structural, not geographic.
# ═════════════════════════════════════════════════════════════

def check_local_seo(report: dict) -> dict:
    """
    Check local SEO signals in a location-agnostic way.

    We check for the STRUCTURE of good local SEO (schema, NAP, geo
    coordinates, location keywords) without assuming any specific city.
    The synthesizer will only surface these for LocalServices sites.
    """
    content = report.get("content", {})
    trust = report.get("trust", {})
    schema = report.get("schema", {})
    meta = report.get("meta", {})

    # NAP: Name, Address, Phone — approximated by phone visibility
    has_nap = trust.get("phone_visible", False)

    has_local_schema = schema.get("local_business_present", False)
    has_geo = schema.get("local_business_has_geo", False)

    # Does the page mention ANY geographic location in prominent places?
    # We detect this by looking for location-pattern signals rather than
    # a hardcoded city list — commas between words (city, state), zip codes,
    # or the word "serving" which signals a service area page.
    import re
    title = (meta.get("title", {}).get("text") or "").lower()
    h1_texts = " ".join(content.get("headings", {}).get("h1", {}).get("texts", [])).lower()
    h2_texts = " ".join(content.get("headings", {}).get("h2", {}).get("texts", [])).lower()
    all_headings = title + " " + h1_texts + " " + h2_texts

    # Zip code, "City, ST" pattern, or explicit service-area language
    has_location_keyword = bool(
        re.search(r"\b\d{5}\b", all_headings) or          # zip code
        re.search(r"[a-z]+,\s+[a-z]{2}\b", all_headings) or  # City, ST
        "serving" in all_headings or
        "service area" in all_headings or
        "near me" in all_headings
    )

    # Reviews: schema or social proof copy
    schema_types = schema.get("types_found", [])
    has_reviews = (
        "AggregateRating" in schema_types
        or "Review" in schema_types
        or trust.get("has_social_proof", False)
    )

    checks = [has_nap, has_local_schema, has_geo,
              has_location_keyword, has_reviews]

    return {
        "nap_present": has_nap,
        "local_business_schema": has_local_schema,
        "schema_has_geo": has_geo,
        "location_keyword_present": has_location_keyword,
        "reviews_indicator": has_reviews,
        "score": sum(1 for c in checks if c),
        "max_score": len(checks),
    }


# ═════════════════════════════════════════════════════════════
# 4. TECHNICAL SEO CHECKLIST
# ═════════════════════════════════════════════════════════════

def build_technical_checklist(report: dict) -> dict:
    meta = report.get("meta", {})
    content = report.get("content", {})
    trust = report.get("trust", {})
    schema = report.get("schema", {})
    site = report.get("site_structure", {})

    title_data = meta.get("title", {})
    desc_data = meta.get("description", {})
    h1_data = content.get("headings", {}).get("h1", {})

    critical = {
        "has_title":            bool(title_data.get("text")),
        "has_meta_description": bool(desc_data.get("text")),
        "has_h1":               h1_data.get("count", 0) >= 1,
        "exactly_one_h1":       h1_data.get("count") == 1,
        "https":                trust.get("https", False),
        "has_canonical":        bool(meta.get("canonical")),
        "has_sitemap":          site.get("sitemap_page_count", 0) > 0,
    }

    important = {
        "has_schema":                  len(schema.get("types_found", [])) > 0,
        "has_open_graph":              bool(meta.get("open_graph")),
        "mobile_viewport":             meta.get("viewport", {}).get("mobile_friendly", False),
        "title_optimal_length":        title_data.get("optimal_length", False),
        "description_optimal_length":  desc_data.get("optimal_length", False),
    }

    nice_to_have = {
        "has_faq":          content.get("faq_present", False),
        "has_author":       content.get("author", {}).get("found", False),
        "has_twitter_card": meta.get("twitter_card", {}).get("present", False),
        "has_dates":        bool(content.get("dates", {}).get("published")),
    }

    return {"critical": critical, "important": important, "nice_to_have": nice_to_have}


# ═════════════════════════════════════════════════════════════
# 5. KEYWORD INFERENCE
# ═════════════════════════════════════════════════════════════

def infer_keywords(report: dict) -> dict:
    title = (report.get("meta", {}).get("title", {}).get("text") or "")
    headings = report.get("content", {}).get("headings", {})
    h1_texts = headings.get("h1", {}).get("texts", [])
    h2_texts = headings.get("h2", {}).get("texts", [])
    primary = h1_texts[0] if h1_texts else title
    secondary = h2_texts[:5]
    return {"primary": primary, "secondary": secondary}


# ═════════════════════════════════════════════════════════════
# 6. CONTENT QUALITY SCORE (0-100)
# ═════════════════════════════════════════════════════════════

def calculate_content_quality_score(report: dict, eeat: dict, technical: dict) -> dict:
    content = report.get("content", {})
    headings = content.get("headings", {})
    schema = report.get("schema", {})
    meta = report.get("meta", {})

    h_total = sum(headings.get(h, {}).get("count", 0) for h in ["h1", "h2", "h3"])
    wc = content.get("word_count", 0)

    structure = 0
    if h_total >= 5: structure += 8
    elif h_total >= 3: structure += 5
    elif h_total >= 1: structure += 2
    if wc >= 500: structure += 8
    elif wc >= 300: structure += 5
    elif wc >= 100: structure += 2
    if headings.get("h1", {}).get("count") == 1: structure += 4
    structure = min(structure, 20)

    eeat_score = round(eeat["total"] / 40 * 25)

    keywords = 0
    title_text = (meta.get("title", {}).get("text") or "").lower()
    h1_texts = [t.lower() for t in headings.get("h1", {}).get("texts", [])]
    if h1_texts and title_text:
        title_words = {w for w in title_text.split() if len(w) > 3}
        h1_words = {w for h in h1_texts for w in h.split() if len(w) > 3}
        if title_words & h1_words:
            keywords += 10
    if meta.get("title", {}).get("optimal_length"): keywords += 5
    if meta.get("description", {}).get("optimal_length"): keywords += 5
    keywords = min(keywords, 20)

    schema_score = 0
    types = schema.get("types_found", [])
    if types: schema_score += 5
    if schema.get("local_business_present"): schema_score += 5
    if schema.get("local_business_has_geo"): schema_score += 3
    if any(t in ["FAQPage", "Article", "Organization", "Product",
                 "SoftwareApplication"] for t in types): schema_score += 2
    schema_score = min(schema_score, 15)

    crit = technical["critical"]
    imp = technical["important"]
    crit_pct = sum(1 for v in crit.values() if v) / max(len(crit), 1)
    imp_pct = sum(1 for v in imp.values() if v) / max(len(imp), 1)
    tech = round(crit_pct * 14 + imp_pct * 6)
    tech = min(tech, 20)

    return {
        "structure": structure,
        "eeat": eeat_score,
        "keywords": keywords,
        "schema": schema_score,
        "technical": tech,
        "total": structure + eeat_score + keywords + schema_score + tech,
    }


# ═════════════════════════════════════════════════════════════
# 7. ISSUES LIST
# ═════════════════════════════════════════════════════════════

def _schema_fix_for_business(report: dict) -> str:
    """
    Return a schema fix recommendation appropriate for this type of site.
    We peek at the robots.txt paths to guess if it's ecommerce.
    """
    robots = " ".join(
        report.get("site_structure", {}).get("robots_disallowed_paths", [])
    ).lower()
    if "woocommerce" in robots or "add-to-cart" in robots or "shopify" in robots:
        return "Add Product and Offer schema to product pages for rich results in Google."
    return "Add structured data (JSON-LD) appropriate for your business type. See schema.org for options."


def collect_issues(report: dict, technical: dict, cwv: dict, local: dict) -> list:
    """
    Build a sorted list of {severity, category, issue, fix} dicts.

    Local SEO issues ARE included here — the synthesizer will filter them
    out for non-local businesses. All fix text is generic (no city names).
    """
    issues = []
    c = technical["critical"]
    i = technical["important"]

    # ── Critical ──
    if not c["has_title"]:
        issues.append({"severity": "critical", "category": "Meta",
            "issue": "Missing <title> tag",
            "fix": "Add a descriptive title 50-60 characters long."})
    if not c["has_meta_description"]:
        issues.append({"severity": "critical", "category": "Meta",
            "issue": "Missing meta description",
            "fix": "Add a meta description 150-160 characters summarizing the page."})
    if not c["has_h1"]:
        issues.append({"severity": "critical", "category": "Content",
            "issue": "No H1 tag on page",
            "fix": "Add a single H1 that clearly states your primary topic or service."})
    elif not c["exactly_one_h1"]:
        issues.append({"severity": "important", "category": "Content",
            "issue": "Multiple H1 tags found",
            "fix": "Use exactly one H1 per page; demote the rest to H2."})
    if not c["https"]:
        issues.append({"severity": "critical", "category": "Security",
            "issue": "Site is not using HTTPS",
            "fix": "Install an SSL certificate and force HTTPS redirects."})
    if not c["has_canonical"]:
        issues.append({"severity": "important", "category": "Meta",
            "issue": "No canonical URL declared",
            "fix": "Add <link rel='canonical' href='...'> to prevent duplicate-content issues."})
    if not c["has_sitemap"]:
        issues.append({"severity": "important", "category": "Technical",
            "issue": "No XML sitemap detected",
            "fix": "Create and submit a sitemap.xml to help search engines find all your pages."})

    # ── Core Web Vitals ──
    for metric, data in cwv.items():
        if data["verdict"] in ("Poor", "Needs Improvement"):
            severity = "critical" if data["verdict"] == "Poor" else "important"
            issues.append({"severity": severity, "category": "Performance",
                "issue": f"{metric.upper()} is {data['verdict']} ({data['value']})",
                "fix": data["recommendation"] or ""})

    # ── Important ──
    if not i["has_schema"]:
        issues.append({"severity": "important", "category": "Schema",
            "issue": "No structured data on page",
            "fix": _schema_fix_for_business(report)})
    if not i["mobile_viewport"]:
        issues.append({"severity": "important", "category": "Mobile",
            "issue": "Missing or incorrect mobile viewport",
            "fix": "Add <meta name='viewport' content='width=device-width, initial-scale=1'>."})
    if not i["has_open_graph"]:
        issues.append({"severity": "important", "category": "Social",
            "issue": "No Open Graph tags",
            "fix": "Add og:title, og:description, and og:image for social sharing previews."})

    # ── Local SEO (only surfaced to user for LocalServices by the synthesizer) ──
    if not local["local_business_schema"]:
        issues.append({"severity": "important", "category": "Local SEO",
            "issue": "No LocalBusiness schema",
            "fix": "Add LocalBusiness JSON-LD including name, address, phone, geo coordinates, and opening hours."})
    if not local["location_keyword_present"]:
        issues.append({"severity": "important", "category": "Local SEO",
            "issue": "No location signals in title or headings",
            "fix": "Include your city or service area in the page title and H1 to improve local search visibility."})

    severity_rank = {"critical": 0, "important": 1, "minor": 2}
    issues.sort(key=lambda x: severity_rank.get(x["severity"], 9))
    return issues


# ═════════════════════════════════════════════════════════════
# MAIN AGENT FUNCTION
# ═════════════════════════════════════════════════════════════

def run(page_report: dict) -> dict:
    eeat = score_eeat(page_report)
    cwv = evaluate_core_web_vitals(page_report)
    local = check_local_seo(page_report)
    technical = build_technical_checklist(page_report)
    keywords = infer_keywords(page_report)
    quality = calculate_content_quality_score(page_report, eeat, technical)
    issues = collect_issues(page_report, technical, cwv, local)

    return {
        "url": page_report.get("url"),
        "eeat": eeat,
        "core_web_vitals": cwv,
        "local_seo": local,
        "technical_checklist": technical,
        "keywords": keywords,
        "content_quality_score": quality,
        "issues": issues,
    }


if __name__ == "__main__":
    import json
    fake_report = {
        "url": "https://joesplumbing.com/",
        "domain": "joesplumbing.com",
        "meta": {
            "title": {"text": "Joe's Plumbing — Trusted Plumber", "length": 35, "optimal_length": False},
            "description": {"text": "Same-day service.", "length": 17, "optimal_length": False},
            "canonical": "https://joesplumbing.com/",
            "open_graph": {"og:title": "Joe's Plumbing"},
            "twitter_card": {"present": True, "card_type": "summary"},
            "viewport": {"present": True, "mobile_friendly": True},
        },
        "content": {
            "headings": {
                "h1": {"count": 1, "texts": ["Plumbing Services, Miami FL"]},
                "h2": {"count": 3, "texts": ["Emergency", "Installs", "FAQ"]},
                "h3": {"count": 0, "texts": []},
            },
            "word_count": 620, "faq_present": True,
            "author": {"name": None, "found": False},
            "dates": {"published": "2024-01-15"},
        },
        "schema": {"types_found": ["Plumber"], "local_business_present": True, "local_business_has_geo": True},
        "links": {"internal_count": 12, "external_count": 3},
        "trust": {
            "https": True, "contact_link": True, "about_link": True,
            "privacy_link": True, "phone_visible": True, "email_visible": True,
            "has_social_proof": True, "social_platforms_linked": ["facebook.com"],
        },
        "tech": {"cms": "WordPress"},
        "pagespeed": {"lcp": None, "cls": None, "inp": None, "performance_category": None},
        "security": {"headers_score": 3, "ssl_expiry_days": 180},
        "site_structure": {"sitemap_page_count": 45, "robots_disallowed_paths": []},
    }
    audit = run(fake_report)
    print(f"Content Quality: {audit['content_quality_score']['total']}/100")
    print(f"Local SEO: {audit['local_seo']['score']}/{audit['local_seo']['max_score']}")
    print(f"\nIssues ({len(audit['issues'])}):")
    for issue in audit["issues"]:
        print(f"  [{issue['severity'].upper()}] {issue['issue']}")
        print(f"     → {issue['fix']}")