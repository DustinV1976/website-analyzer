"""
Business Decoder Agent
======================

Reads a PAGE_INSPECTOR_REPORT and decodes the business behind the website:

  - Business model classification (SaaS / Ecommerce / LocalServices / Agency / Media / LeadGen)
  - Audience signals (language complexity, price sensitivity, geographic focus, company size)
  - Funnel mapping (awareness / consideration / conversion / retention — which stages exist)
  - Positioning (primary promise, differentiators, proof elements, brand tone)
  - Competitive signals (mentioned domains, conspicuous content gaps)

This is the most subjective of the three agents — its outputs are heuristic
guesses based on text patterns, not strict yes/no signals. We capture
confidence levels so the synthesizer knows how much to trust each finding.

Usage:
    from agents.business_decoder import run
    decoded = run(page_inspector_report)
"""

from urllib.parse import urlparse


# ═════════════════════════════════════════════════════════════
# CONFIGURATION — signal dictionaries
# Tune these as you analyze more sites and see which signals fire correctly.
# ═════════════════════════════════════════════════════════════

# Each business model has signature keywords, schema types, and CMS hints.
BUSINESS_MODEL_SIGNALS = {
    "SaaS": {
        "keywords": ["software", "platform", "dashboard", "api", "integration",
                     "free trial", "start free", "start for free", "try free",
                     "request demo", "pricing plan", "sign up free", "no credit card",
                     "subscription", "per month", "per user", "cancel anytime",
                     "free plan", "upgrade", "downgrade",
                     # B2B product / project-management vocabulary
                     "workspace", "issue tracking", "project management",
                     "roadmap", "workflow", "collaborate", "product teams",
                     "sprint", "backlog", "deployment", "release",
                     "saas", "cloud-based", "cloud based"],
        "schema_types": ["SoftwareApplication"],
        "cms_hints": [],
    },
    "Ecommerce": {
        "keywords": ["add to cart", "shop now", "free shipping", "checkout",
                     "in stock", "buy now", "your cart", "wishlist"],
        "schema_types": ["Product", "Offer", "Store"],
        "cms_hints": ["Shopify"],
    },
    "LocalServices": {
        "keywords": [
            # booking/contact actions
            "call now", "call us", "call today", "schedule", "book online",
            "book an appointment", "request an appointment", "free estimate",
            "free consultation", "same day", "24/7", "emergency",
            # trust/credentials
            "licensed", "insured", "licensed and insured", "family owned",
            "family-owned", "serving", "service area", "near me",
            # industry terms — broad set so any trade/health/food vertical matches
            "plumbing", "plumber", "drain", "hvac", "heating", "cooling",
            "roofing", "electrician", "electrical", "locksmith", "pest control",
            "landscaping", "lawn care", "cleaning service", "mold",
            "dental", "dentist", "orthodontic", "teeth whitening",
            "restaurant", "menu", "dine in", "takeout",
            "attorney", "law firm", "personal injury",
            "salon", "day spa", "massage", "med spa", "dermatology",
            "auto repair", "oil change", "tire",
        ],
        "schema_types": ["LocalBusiness", "Plumber", "Dentist", "Restaurant",
                         "HomeAndConstructionBusiness", "HVACBusiness",
                         "AutoRepair", "LegalService", "MedicalBusiness",
                         "BeautySalon", "FoodEstablishment"],
        "cms_hints": [],
    },
    "Agency": {
        "keywords": ["our work", "case studies", "portfolio", "our clients",
                     "we partner", "our team", "agency"],
        "schema_types": ["ProfessionalService"],
        "cms_hints": [],
    },
    "Media": {
        "keywords": ["category", "subscribe", "newsletter", "latest articles",
                     "popular posts", "by the editors"],
        "schema_types": ["NewsArticle", "Article", "BlogPosting"],
        "cms_hints": [],
    },
    "LeadGen": {
        "keywords": ["get a quote", "free consultation", "request information",
                     "talk to sales", "speak with an expert", "request a demo"],
        "schema_types": [],
        "cms_hints": [],
    },
}

# Funnel stages — keywords/schema indicating each stage is present on the page
FUNNEL_STAGES = {
    "awareness": {
        "keywords": ["blog", "article", "guide", "how to", "what is", "learn",
                     "resources", "ultimate guide"],
        "schema": ["BlogPosting", "Article", "NewsArticle"],
    },
    "consideration": {
        "keywords": ["features", "compare", " vs ", "case study", "case studies",
                     "testimonial", "review", "demo", "how it works"],
        "schema": ["AggregateRating", "Review"],
    },
    "conversion": {
        "keywords": ["pricing", "buy", "checkout", "cart", "free trial",
                     "get started", "sign up", "schedule", "book now",
                     "get a quote", "contact us", "call now"],
        "schema": ["Offer", "Product"],
    },
    "retention": {
        "keywords": ["help", "support", "documentation", " docs ", "login",
                     "log in", "my account", "customer portal", "knowledge base"],
        "schema": [],
    },
}

# Price-positioning vocabulary
PRICE_INDICATORS = {
    "budget":  ["cheap", "affordable", "low cost", "budget", "discount", "save"],
    "premium": ["luxury", "premium", "high-end", "elite", "exclusive",
                "bespoke", "concierge", "white-glove"],
}

# Company-size targeting vocabulary
ENTERPRISE_INDICATORS = ["enterprise", "fortune 500", "soc 2", "iso 27001",
                         "sla", "dedicated support", "compliance", "sso"]
SMB_INDICATORS        = ["small business", "smb", "startup", "growing team"]
CONSUMER_INDICATORS   = ["family", "personal", "home", "individual"]

# Geographic-focus indicators (small set for this agent — see seo_auditor for full FL list)
LOCAL_GEO_INDICATORS         = ["fort lauderdale", "broward", "south florida",
                                "near me", "service area"]
INTERNATIONAL_GEO_INDICATORS = ["international", "global", "worldwide",
                                "multi-language", "ships worldwide"]

# Tone vocabulary
CASUAL_TONE_WORDS    = ["awesome", "amazing", "love", "easy peasy", "yay", "rad"]
CORPORATE_TONE_WORDS = ["proprietary", "enterprise-grade", "robust", "leverage",
                        "synergy", "best-in-class"]


# ═════════════════════════════════════════════════════════════
# SHARED HELPER
# ═════════════════════════════════════════════════════════════

def _extract_all_text(report: dict) -> str:
    """Concatenate all available text signals in lowercase for keyword matching."""
    parts = []
    meta = report.get("meta", {})
    parts.append(meta.get("title", {}).get("text") or "")
    parts.append(meta.get("description", {}).get("text") or "")

    headings = report.get("content", {}).get("headings", {})
    for level in ["h1", "h2", "h3"]:
        parts.extend(headings.get(level, {}).get("texts", []))

    parts.append(report.get("content", {}).get("body_snippet") or "")

    return " ".join(parts).lower()


# ═════════════════════════════════════════════════════════════
# 1. BUSINESS MODEL CLASSIFICATION
# ═════════════════════════════════════════════════════════════

def classify_business_model(report: dict) -> dict:
    """
    Score every model against the page's signals and pick the top one.

    Schema types count for 3 points (strong signal), keyword matches for 1,
    CMS hints for 2. Robots path signals for 3 (very reliable fingerprint).
    Confidence comes from the margin between top and second.
    """
    text = _extract_all_text(report)
    schema_types = report.get("schema", {}).get("types_found", [])
    cms = report.get("tech", {}).get("cms", "")

    # robots.txt disallowed paths are reliable platform fingerprints —
    # platforms write them, not humans, so they're hard to accidentally fake.
    robots_paths = " ".join(
        report.get("site_structure", {}).get("robots_disallowed_paths", [])
    ).lower()

    # Strong ecommerce signals hiding in robots.txt that keyword scanning misses
    ECOMMERCE_ROBOTS_SIGNALS = [
        "woocommerce", "add-to-cart", "shopify", "/cart", "/checkout",
        "wc-logs", "woocommerce_uploads",
    ]

    scores = {}
    for model, signals in BUSINESS_MODEL_SIGNALS.items():
        score = 0
        score += sum(1 for kw in signals["keywords"] if kw in text)
        score += sum(3 for st in signals["schema_types"] if st in schema_types)
        score += sum(2 for ch in signals["cms_hints"] if ch == cms)
        # Extra check: ecommerce fingerprints in robots.txt paths
        if model == "Ecommerce":
            score += sum(3 for sig in ECOMMERCE_ROBOTS_SIGNALS if sig in robots_paths)
        scores[model] = score

    # A visible phone number is a strong local-services signal — no SaaS or
    # ecommerce site leads with a phone number the way a plumber or dentist does.
    if report.get("trust", {}).get("phone_visible"):
        scores["LocalServices"] = scores.get("LocalServices", 0) + 2

    # SoftwareApplication schema is an unambiguous SaaS signal — give it a
    # decisive boost so it wins even when ecommerce schema is also present
    # (e.g. a SaaS platform that uses Product/Offer schema for pricing plans).
    if "SoftwareApplication" in schema_types:
        scores["SaaS"] = scores.get("SaaS", 0) + 6

    # If nothing scored, we genuinely don't know
    if not any(scores.values()):
        return {"primary": "Unknown", "confidence": "low", "scores": scores}

    # Pick top model
    sorted_models = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_model, top_score = sorted_models[0]
    second_score = sorted_models[1][1] if len(sorted_models) > 1 else 0
    margin = top_score - second_score

    # Confidence: strong winner with clear margin = high
    if top_score >= 5 and margin >= 2:
        confidence = "high"
    elif top_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {"primary": top_model, "confidence": confidence, "scores": scores}


# ═════════════════════════════════════════════════════════════
# 2. AUDIENCE SIGNALS
# ═════════════════════════════════════════════════════════════

def analyze_audience(report: dict) -> dict:
    """Decode who this page is written FOR."""
    text = _extract_all_text(report)

    # ── Language complexity (from readability score, if available) ──
    readability = report.get("content", {}).get("readability_grade")
    if isinstance(readability, dict):
        language_complexity = readability.get("audience", "unknown")
    else:
        language_complexity = "unknown"

    # ── Price sensitivity ──
    budget_hits = sum(1 for kw in PRICE_INDICATORS["budget"] if kw in text)
    premium_hits = sum(1 for kw in PRICE_INDICATORS["premium"] if kw in text)
    if premium_hits > budget_hits and premium_hits >= 2:
        price_sensitivity = "premium"
    elif budget_hits > premium_hits and budget_hits >= 2:
        price_sensitivity = "budget"
    else:
        price_sensitivity = "mid-market"

    # ── Geographic focus ──
    local_hits = sum(1 for term in LOCAL_GEO_INDICATORS if term in text)
    intl_hits = sum(1 for term in INTERNATIONAL_GEO_INDICATORS if term in text)
    if local_hits >= 2:
        geographic_focus = "local"
    elif intl_hits >= 1:
        geographic_focus = "international"
    else:
        geographic_focus = "national"

    # ── Company size target ──
    ent_hits = sum(1 for kw in ENTERPRISE_INDICATORS if kw in text)
    smb_hits = sum(1 for kw in SMB_INDICATORS if kw in text)
    cons_hits = sum(1 for kw in CONSUMER_INDICATORS if kw in text)

    if ent_hits >= 2:
        company_size_target = "enterprise"
    elif smb_hits >= 1:
        company_size_target = "SMB"
    elif cons_hits >= 2:
        company_size_target = "consumer"
    else:
        company_size_target = "unknown"

    return {
        "language_complexity": language_complexity,
        "price_sensitivity": price_sensitivity,
        "geographic_focus": geographic_focus,
        "company_size_target": company_size_target,
    }


# ═════════════════════════════════════════════════════════════
# 3. FUNNEL MAPPING
# ═════════════════════════════════════════════════════════════

def map_funnel(report: dict) -> dict:
    """Which funnel stages are represented on this page, and how strongly?"""
    text = _extract_all_text(report)
    schema_types = report.get("schema", {}).get("types_found", [])

    result = {}
    for stage, signals in FUNNEL_STAGES.items():
        present = []
        for kw in signals["keywords"]:
            if kw in text:
                present.append(kw.strip())
        for st in signals["schema"]:
            if st in schema_types:
                present.append(f"schema:{st}")

        # Classify the stage strength
        count = len(present)
        if count == 0:    strength = "missing"
        elif count == 1:  strength = "thin"
        elif count <= 3:  strength = "present"
        else:             strength = "strong"

        result[stage] = {"strength": strength, "signals": present}

    return result


# ═════════════════════════════════════════════════════════════
# 4. POSITIONING
# ═════════════════════════════════════════════════════════════

def analyze_positioning(report: dict) -> dict:
    """Decode what the brand is promising and how it stands out."""
    title = report.get("meta", {}).get("title", {}).get("text") or ""
    h1_texts = report.get("content", {}).get("headings", {}).get("h1", {}).get("texts", [])
    text = _extract_all_text(report)

    # Primary promise — strongest signal is H1, fall back to title
    primary_promise = h1_texts[0] if h1_texts else title

    # Differentiator phrases — these signal a positioning claim
    differentiator_phrases = [
        "the only", "the first", "the leader", "the #1", "the number one",
        "unlike", "we don't", "patented", "award-winning", "industry-leading",
    ]
    differentiators = [p for p in differentiator_phrases if p in text]

    # Proof elements
    schema_types = report.get("schema", {}).get("types_found", [])
    proof_elements = {
        "testimonials": "testimonial" in text or "what our clients say" in text,
        "case_studies": "case study" in text or "case studies" in text,
        "ratings":      "AggregateRating" in schema_types or "Review" in schema_types,
        "client_logos": "trusted by" in text or "our clients" in text,
    }

    # Brand tone — quick heuristic blend
    casual_hits = sum(1 for w in CASUAL_TONE_WORDS if w in text)
    corp_hits = sum(1 for w in CORPORATE_TONE_WORDS if w in text)

    readability = report.get("content", {}).get("readability_grade")
    audience = readability.get("audience") if isinstance(readability, dict) else None

    if casual_hits >= 2:
        brand_tone = "casual"
    elif corp_hits >= 2:
        brand_tone = "corporate"
    elif audience == "specialist":
        brand_tone = "technical"
    else:
        brand_tone = "professional"

    return {
        "primary_promise": primary_promise,
        "differentiators": differentiators,
        "proof_elements": proof_elements,
        "brand_tone": brand_tone,
    }


# ═════════════════════════════════════════════════════════════
# 5. COMPETITIVE SIGNALS
# ═════════════════════════════════════════════════════════════

# Domains we want to ignore when listing "mentioned" domains
NOISE_DOMAINS = [
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "tiktok.com", "googleapis.com", "gstatic.com",
    "googletagmanager.com", "google-analytics.com", "fonts.googleapis.com",
]


def analyze_competitive(report: dict) -> dict:
    """
    Who does the page link out to? What are they conspicuously NOT covering?

    External domains often reveal partners, integrations, or competitors.
    Missing topics (like pricing or comparisons) often reveal positioning gaps.
    """
    external_links = report.get("links", {}).get("external", [])

    # Extract clean domain names, filter out social media + CDN noise
    domains = set()
    for link in external_links:
        try:
            domain = urlparse(link).netloc.lower().replace("www.", "")
            if domain and not any(noise in domain for noise in NOISE_DOMAINS):
                domains.add(domain)
        except Exception:
            continue

    # Conspicuous content gaps — common "things a healthy site should mention"
    text = _extract_all_text(report)
    gaps = []
    if not any(w in text for w in ["price", "pricing", "cost", "rate", "$"]):
        gaps.append("No pricing or cost transparency")
    if not any(w in text for w in ["compare", " vs ", "alternative", "instead of"]):
        gaps.append("No competitive comparison content")
    if not any(w in text for w in ["customer", "client", "testimonial",
                                    "review", "trusted by"]):
        gaps.append("No customer or social proof mentions")
    if not any(w in text for w in ["about us", "our team", "founder", "ceo"]):
        gaps.append("No 'about us' or team mentions")

    return {
        "mentioned_domains": sorted(domains)[:10],
        "conspicuous_gaps": gaps,
    }


# ═════════════════════════════════════════════════════════════
# MAIN AGENT FUNCTION
# ═════════════════════════════════════════════════════════════

def run(page_report: dict) -> dict:
    """
    Decode the business behind a webpage.

    Args:
        page_report: the dict returned by page_inspector.run()

    Returns:
        A BUSINESS_DECODER_REPORT dict with model, audience, funnel,
        positioning, and competitive signals.
    """
    return {
        "url": page_report.get("url"),
        "business_model": classify_business_model(page_report),
        "audience": analyze_audience(page_report),
        "funnel": map_funnel(page_report),
        "positioning": analyze_positioning(page_report),
        "competitive_signals": analyze_competitive(page_report),
    }


# ─────────────────────────────────────────────────────────────
# QUICK TEST
# Uses a fake PAGE_INSPECTOR_REPORT so the file runs standalone.
# Run with:  python scripts/agents/business_decoder.py
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    fake_report = {
        "url": "https://joesplumbing.com/",
        "meta": {
            "title": {"text": "Joe's Plumbing — Fort Lauderdale's Trusted Plumber"},
            "description": {"text": "Same-day emergency plumbing. Licensed and insured. Serving Fort Lauderdale and Broward County. Call now for a free estimate."},
        },
        "content": {
            "headings": {
                "h1": {"count": 1, "texts": ["Fort Lauderdale Plumbing Services"]},
                "h2": {"count": 3, "texts": ["Emergency Service Same Day",
                                             "What Our Clients Say",
                                             "Schedule a Free Estimate"]},
                "h3": {"count": 0, "texts": []},
            },
            "readability_grade": {"grade_level": 7.0, "audience": "general consumer"},
        },
        "schema": {"types_found": ["Plumber", "AggregateRating"]},
        "links": {
            "external_count": 3,
            "external": [
                "https://facebook.com/joesplumbing",
                "https://yelp.com/biz/joes-plumbing",
                "https://bbb.org/florida/joes-plumbing",
            ],
        },
        "trust": {"has_social_proof": True},
        "tech": {"cms": "WordPress"},
    }

    decoded = run(fake_report)

    print("── BUSINESS MODEL ──")
    bm = decoded["business_model"]
    print(f"  Primary:    {bm['primary']}  (confidence: {bm['confidence']})")
    print(f"  All scores: {bm['scores']}")

    print("\n── AUDIENCE ──")
    print(json.dumps(decoded["audience"], indent=2))

    print("\n── FUNNEL ──")
    for stage, data in decoded["funnel"].items():
        print(f"  {stage:14s} {data['strength']:8s}  signals: {data['signals']}")

    print("\n── POSITIONING ──")
    pos = decoded["positioning"]
    print(f"  Primary promise:  {pos['primary_promise']}")
    print(f"  Differentiators:  {pos['differentiators']}")
    print(f"  Brand tone:       {pos['brand_tone']}")
    print(f"  Proof elements:   {pos['proof_elements']}")

    print("\n── COMPETITIVE ──")
    comp = decoded["competitive_signals"]
    print(f"  Mentioned domains: {comp['mentioned_domains']}")
    print(f"  Conspicuous gaps:  {comp['conspicuous_gaps']}")