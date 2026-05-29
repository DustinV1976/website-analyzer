"""
Synthesizer Agent
=================

The final agent. Takes the outputs of the other three agents and combines
them into a single FINAL_REPORT that the Streamlit UI will display.

What it produces:
  - Site Intelligence Score (0-100) broken into 4 weighted categories
  - A letter grade (A-F) for easy at-a-glance evaluation
  - All issues re-sorted by *business impact*, not just technical severity
  - Quick Wins (top 3 low-effort, high-impact items)
  - Strategic Recommendations (top 3 high-effort, high-impact items)
  - A one-paragraph summary capturing the most important finding

Usage:
    from agents.synthesizer import run
    final = run(page_report, seo_report, business_report)
"""

from datetime import datetime


# ═════════════════════════════════════════════════════════════
# 1. SITE INTELLIGENCE SCORE — four weighted components
# ═════════════════════════════════════════════════════════════

def calculate_seo_health(seo_report: dict) -> int:
    """SEO Health = 30 pts, scaled from the SEO Auditor's content quality score."""
    quality = seo_report.get("content_quality_score", {}).get("total", 0)
    return round(quality / 100 * 30)


def calculate_technical_health(seo_report: dict) -> int:
    """Technical Health = 25 pts from technical checklist + Core Web Vitals."""
    technical = seo_report.get("technical_checklist", {})
    critical = technical.get("critical", {})
    important = technical.get("important", {})

    # Critical checks carry more weight than important ones
    crit_pct = sum(1 for v in critical.values() if v) / max(len(critical), 1)
    imp_pct = sum(1 for v in important.values() if v) / max(len(important), 1)
    score = round(crit_pct * 15 + imp_pct * 7)

    # Bonus: one point per Core Web Vital scoring "Good"
    cwv = seo_report.get("core_web_vitals", {})
    cwv_bonus = sum(1 for d in cwv.values() if d.get("verdict") == "Good")

    return min(score + cwv_bonus, 25)


def calculate_business_clarity(business_report: dict) -> int:
    """Business Clarity = 25 pts: classification confidence + funnel + positioning."""
    # ── Business model classification confidence (10 pts) ──
    confidence_map = {"high": 10, "medium": 6, "low": 2}
    bm_score = confidence_map.get(
        business_report.get("business_model", {}).get("confidence"), 0
    )

    # ── Funnel coverage (10 pts) ──
    funnel = business_report.get("funnel", {})
    strength_map = {"strong": 3, "present": 2, "thin": 1, "missing": 0}
    funnel_raw = sum(strength_map.get(s.get("strength"), 0) for s in funnel.values())
    funnel_score = min(funnel_raw, 10)

    # ── Positioning clarity (5 pts) ──
    positioning = business_report.get("positioning", {})
    pos_score = 0
    if positioning.get("differentiators"):
        pos_score += 2
    proof = positioning.get("proof_elements", {})
    pos_score += min(sum(1 for v in proof.values() if v), 3)

    return min(bm_score + funnel_score + pos_score, 25)


def calculate_trust_signals(page_report: dict, seo_report: dict) -> int:
    """Trust Signals = 20 pts: E-E-A-T trustworthiness + page-level trust elements."""
    # E-E-A-T trustworthiness pillar already scored 0-10
    trust_eeat = seo_report.get("eeat", {}).get("trustworthiness", 0)

    # Page-level trust elements
    trust = page_report.get("trust", {})
    elements = 0
    if trust.get("https"): elements += 2
    if trust.get("contact_link"): elements += 2
    if trust.get("privacy_link"): elements += 1
    if trust.get("phone_visible"): elements += 2
    if trust.get("social_platforms_linked"): elements += 2
    if trust.get("has_social_proof"): elements += 1

    return min(trust_eeat + elements, 20)


def assign_grade(total_score: int) -> str:
    """Letter grade from total 0-100 score."""
    if total_score >= 90: return "A"
    if total_score >= 80: return "B"
    if total_score >= 70: return "C"
    if total_score >= 60: return "D"
    return "F"


# ═════════════════════════════════════════════════════════════
# 2. BUSINESS IMPACT SCORING & EFFORT ESTIMATION
# These re-rank the raw issues list by what actually moves the needle.
# ═════════════════════════════════════════════════════════════

def score_business_impact(issue: dict) -> int:
    """
    Score an issue's business impact 1-10.

    Severity gives us the base. Then we add boosts for issue types that
    directly hurt conversions, trust, or local discoverability — those
    matter more than abstract technical hygiene.
    """
    category = issue.get("category", "")
    severity = issue.get("severity", "")
    text = issue.get("issue", "").lower()

    # Base score from severity
    base = {"critical": 7, "important": 4, "minor": 1}.get(severity, 1)

    # Boost: trust-killers are the worst — broken HTTPS, missing contact info
    if category == "Security":
        base += 3
    # Boost: local SEO matters more for our Fort Lauderdale targets
    if category == "Local SEO":
        base += 2
    # Boost: performance affects bounce rate AND rankings
    if category == "Performance":
        base += 1
    # Boost: discovery-blockers
    if any(kw in text for kw in ["title", "h1", "canonical"]):
        base += 1

    return min(base, 10)


def estimate_effort(issue: dict) -> str:
    """Rough effort estimate: 'low' / 'medium' / 'high'."""
    text = issue.get("issue", "").lower()
    category = issue.get("category", "")

    # Low-effort: things that are just adding or fixing a tag
    low_signals = ["meta description", "canonical", "viewport", "open graph",
                   "twitter card", "title tag", "missing <title>",
                   "missing h1", "no h1", "multiple h1",
                   "sitemap", "robots.txt"]
    if any(s in text for s in low_signals):
        return "low"

    # High-effort: performance work, content production, structural change
    if category == "Performance":
        return "high"
    if any(s in text for s in ["case stud", "blog", "ongoing content"]):
        return "high"

    # Schema and local SEO sit in the middle — research + write JSON-LD
    if category in ("Schema", "Local SEO"):
        return "medium"

    return "medium"


def filter_issues_by_business_model(issues: list, business_model: str) -> list:
    """
    Strip irrelevant issues based on what kind of business this is.

    Local SEO checks (Fort Lauderdale location, LocalBusiness schema) only
    make sense for LocalServices sites. For ecommerce, SaaS, media, etc.,
    those recommendations would be wrong and confusing.
    """
    if business_model == "LocalServices":
        return issues  # keep everything for local businesses

    # For all other business types, remove Local SEO issues entirely
    return [i for i in issues if i.get("category") != "Local SEO"]


def annotate_issues(issues: list) -> list:
    """Attach effort and impact to every issue, then sort by impact (desc)."""
    annotated = []
    for issue in issues:
        annotated.append({
            **issue,
            "effort": estimate_effort(issue),
            "impact": score_business_impact(issue),
        })
    annotated.sort(key=lambda x: -x["impact"])
    return annotated


def select_recommendations(annotated_issues: list) -> dict:
    """
    Pick top 3 Quick Wins (low-effort, high-impact) and top 3 Strategic
    Recommendations (high-effort, high-impact). Both lists are sorted by impact.

    If we run out of low-effort issues, we backfill from medium-effort —
    better to surface SOMETHING actionable than leave the list short.
    """
    quick_wins = [i for i in annotated_issues if i["effort"] == "low"][:3]
    if len(quick_wins) < 3:
        backfill = [i for i in annotated_issues
                    if i["effort"] == "medium" and i not in quick_wins]
        quick_wins.extend(backfill[: 3 - len(quick_wins)])

    strategic = [i for i in annotated_issues if i["effort"] == "high"][:3]
    if len(strategic) < 3:
        backfill = [i for i in annotated_issues
                    if i["effort"] == "medium"
                    and i["impact"] >= 5
                    and i not in strategic
                    and i not in quick_wins]
        strategic.extend(backfill[: 3 - len(strategic)])

    return {"quick_wins": quick_wins, "strategic_recommendations": strategic}


# ═════════════════════════════════════════════════════════════
# 3. BUSINESS SIGNAL → ISSUES CONVERSION
# ═════════════════════════════════════════════════════════════

def issues_from_business_report(business_report: dict) -> list:
    """Turn business decoder findings into issues for the ranking pipeline."""
    issues = []
    proof = business_report.get("positioning", {}).get("proof_elements", {})
    funnel = business_report.get("funnel", {})
    differentiators = business_report.get("positioning", {}).get("differentiators", [])

    if not proof.get("testimonials"):
        issues.append({"severity": "important", "category": "Trust",
            "issue": "No testimonials on page",
            "fix": "Add 3-5 customer testimonials with names and photos."})
    if not proof.get("case_studies"):
        issues.append({"severity": "important", "category": "Content",
            "issue": "No case studies or success stories",
            "fix": "Publish 2-3 case studies showing real client outcomes."})
    if not proof.get("ratings"):
        issues.append({"severity": "important", "category": "Trust",
            "issue": "No ratings or review count displayed",
            "fix": "Show star ratings or a review count pulled from Google or Yelp."})
    if not proof.get("client_logos"):
        issues.append({"severity": "minor", "category": "Trust",
            "issue": "No client logos or partner badges",
            "fix": "Add a logo strip of recognisable clients or partners."})
    if not differentiators:
        issues.append({"severity": "important", "category": "Content",
            "issue": "No clear differentiators on page",
            "fix": "State 2-3 reasons why a visitor should choose you over competitors."})

    funnel_fixes = {
        "awareness":     "Add educational content (blog posts, guides, or videos) to attract top-of-funnel visitors.",
        "consideration": "Add comparison content, FAQs, or a 'Why us?' section to help visitors evaluate you.",
        "conversion":    "Add a clear call-to-action (form, booking link, or phone number) above the fold.",
        "retention":     "Add a newsletter sign-up or loyalty touchpoint to stay in contact after the first visit.",
    }
    for stage, data in funnel.items():
        strength = data.get("strength", "present")
        if strength in ("missing", "thin"):
            severity = "important" if strength == "missing" else "minor"
            issues.append({"severity": severity, "category": "Content",
                "issue": f"{stage.title()}-stage funnel content is {strength}",
                "fix": funnel_fixes.get(stage, f"Strengthen your {stage} content.")})

    return issues


# ═════════════════════════════════════════════════════════════
# 4. MAIN AGENT FUNCTION
# ═════════════════════════════════════════════════════════════

def run(page_report: dict, seo_report: dict, business_report: dict) -> dict:
    """
    Synthesize the three agent reports into the final analysis.

    Args:
        page_report:     output of page_inspector.run()
        seo_report:      output of seo_auditor.run()
        business_report: output of business_decoder.run()

    Returns:
        A FINAL_REPORT dict containing the score, recommendations, and
        all three source reports embedded for the UI to drill into.
    """
    # ── Score the four components ──
    seo_health = calculate_seo_health(seo_report)
    tech_health = calculate_technical_health(seo_report)
    business_clarity = calculate_business_clarity(business_report)
    trust_signals = calculate_trust_signals(page_report, seo_report)
    total = seo_health + tech_health + business_clarity + trust_signals

    # ── Re-rank issues by business impact, then pick top recommendations ──
    bm = business_report.get("business_model", {})
    business_model = bm.get("primary", "Unknown")

    # Filter out irrelevant issue categories before ranking, then fold in
    # business-signal issues (trust gaps, funnel holes, missing proof elements)
    relevant_issues = filter_issues_by_business_model(
        seo_report.get("issues", []), business_model
    )
    all_issues = relevant_issues + issues_from_business_report(business_report)
    annotated = annotate_issues(all_issues)
    recs = select_recommendations(annotated)

    # ── Build the one-line summary ──
    pos = business_report.get("positioning", {})
    biggest = annotated[0]["issue"] if annotated else "No issues found"

    return {
        "url": page_report.get("url"),
        "domain": page_report.get("domain"),
        "analysis_date": datetime.now().isoformat(),

        "site_intelligence_score": {
            "total": total,
            "grade": assign_grade(total),
            "seo_health": seo_health,
            "technical_health": tech_health,
            "business_clarity": business_clarity,
            "trust_signals": trust_signals,
        },

        "summary": {
            "business_model": bm.get("primary"),
            "model_confidence": bm.get("confidence"),
            "primary_promise": pos.get("primary_promise"),
            "biggest_opportunity": biggest,
        },

        "quick_wins": recs["quick_wins"],
        "strategic_recommendations": recs["strategic_recommendations"],
        "all_issues_by_impact": annotated,

        # Embed the source reports so the UI can drill in for detail views
        "page_report": page_report,
        "seo_audit": seo_report,
        "business_decoder": business_report,
    }


# ─────────────────────────────────────────────────────────────
# QUICK TEST
# Uses a more realistic "mediocre site" example with several issues
# so we can see Quick Wins and Strategic Recommendations populated.
# Run with:  python scripts/agents/synthesizer.py
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ── Fake page report for a Fort Lauderdale dentist with some issues ──
    fake_page = {
        "url": "https://example-dentist.com/",
        "domain": "example-dentist.com",
        "trust": {
            "https": True, "contact_link": True, "about_link": True,
            "privacy_link": False, "phone_visible": True, "email_visible": False,
            "has_social_proof": False, "social_platforms_linked": ["facebook.com"],
        },
    }

    # ── Fake SEO audit with multiple issues at different severities ──
    fake_seo = {
        "url": "https://example-dentist.com/",
        "eeat": {"experience": 5, "expertise": 3, "authoritativeness": 6,
                 "trustworthiness": 8, "total": 22},
        "core_web_vitals": {
            "lcp": {"value": 4.5, "verdict": "Poor",
                    "recommendation": "LCP is very slow. Compress images, defer JS."},
            "cls": {"value": 0.08, "verdict": "Good", "recommendation": None},
            "inp": {"value": 250, "verdict": "Needs Improvement",
                    "recommendation": "Reduce main-thread work."},
        },
        "technical_checklist": {
            "critical": {"has_title": True, "has_meta_description": False,
                         "has_h1": True, "exactly_one_h1": True, "https": True,
                         "has_canonical": False, "has_sitemap": True},
            "important": {"has_schema": False, "has_open_graph": False,
                          "mobile_viewport": True, "title_optimal_length": True,
                          "description_optimal_length": False},
            "nice_to_have": {"has_faq": False, "has_author": False,
                             "has_twitter_card": False, "has_dates": False},
        },
        "content_quality_score": {"structure": 12, "eeat": 14, "keywords": 10,
                                   "schema": 0, "technical": 12, "total": 48},
        "issues": [
            {"severity": "critical", "category": "Meta",
             "issue": "Missing meta description",
             "fix": "Add a meta description 150-160 chars summarizing the page."},
            {"severity": "important", "category": "Meta",
             "issue": "No canonical URL declared",
             "fix": "Add <link rel='canonical'> to prevent duplicate-content issues."},
            {"severity": "critical", "category": "Performance",
             "issue": "LCP is Poor (4.5)",
             "fix": "LCP is very slow. Compress images, defer JS."},
            {"severity": "important", "category": "Schema",
             "issue": "No structured data on page",
             "fix": "Add LocalBusiness JSON-LD with name, address, phone, and hours."},
            {"severity": "important", "category": "Local SEO",
             "issue": "No LocalBusiness schema",
             "fix": "Add LocalBusiness JSON-LD — critical for local search rankings."},
            {"severity": "important", "category": "Social",
             "issue": "No Open Graph tags",
             "fix": "Add og:title, og:description, og:image for social sharing."},
        ],
    }

    # ── Fake business decoder report ──
    fake_business = {
        "url": "https://example-dentist.com/",
        "business_model": {"primary": "LocalServices", "confidence": "medium",
                           "scores": {"LocalServices": 4, "Agency": 0}},
        "positioning": {
            "primary_promise": "Family Dentistry in Fort Lauderdale",
            "differentiators": [],
            "proof_elements": {"testimonials": False, "case_studies": False,
                               "ratings": False, "client_logos": False},
        },
        "funnel": {
            "awareness": {"strength": "missing", "signals": []},
            "consideration": {"strength": "thin", "signals": ["review"]},
            "conversion": {"strength": "present", "signals": ["schedule", "call now"]},
            "retention": {"strength": "missing", "signals": []},
        },
    }

    final = run(fake_page, fake_seo, fake_business)

    score = final["site_intelligence_score"]
    print("╔════════════════════════════════════════╗")
    print(f"║  SITE INTELLIGENCE SCORE: {score['total']:>3d}/100  ({score['grade']})  ║")
    print("╠════════════════════════════════════════╣")
    print(f"║  SEO Health:        {score['seo_health']:>2d}/30              ║")
    print(f"║  Technical Health:  {score['technical_health']:>2d}/25              ║")
    print(f"║  Business Clarity:  {score['business_clarity']:>2d}/25              ║")
    print(f"║  Trust Signals:     {score['trust_signals']:>2d}/20              ║")
    print("╚════════════════════════════════════════╝")

    print(f"\n── SUMMARY ──")
    print(f"  Business model:        {final['summary']['business_model']} "
          f"(confidence: {final['summary']['model_confidence']})")
    print(f"  Primary promise:       {final['summary']['primary_promise']}")
    print(f"  Biggest opportunity:   {final['summary']['biggest_opportunity']}")

    print(f"\n── QUICK WINS (low effort, high impact) ──")
    for i, win in enumerate(final["quick_wins"], 1):
        print(f"  {i}. [impact {win['impact']}] {win['issue']}")
        print(f"     → {win['fix']}")

    print(f"\n── STRATEGIC RECOMMENDATIONS (high effort, high impact) ──")
    for i, rec in enumerate(final["strategic_recommendations"], 1):
        print(f"  {i}. [impact {rec['impact']}] {rec['issue']}")
        print(f"     → {rec['fix']}")