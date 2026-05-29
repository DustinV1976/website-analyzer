"""
AVE — Website Analyzer
======================
Streamlit UI for the 4-agent SEO analysis engine.
"""

import json
import os
import sys
from pathlib import Path

# Must be set before chromadb is imported — fixes protobuf version conflict on Streamlit Cloud
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from scripts.agents.page_inspector import run as run_page_inspector
from scripts.agents.seo_auditor import run as run_seo_auditor
from scripts.agents.business_decoder import run as run_business_decoder
from scripts.agents.synthesizer import run as run_synthesizer
from scripts.db import init_db, save_analysis, get_all_analyses, get_analysis
from scripts.vector_store import (
    init_chroma, store_page, store_sections, store_issues,
    find_similar_sites, find_content_gaps, find_solved_problems,
)
from urllib.parse import urlparse


# ─────────────────────────────────────────────────────────────
# ONE-TIME BOOTSTRAP
# ─────────────────────────────────────────────────────────────

@st.cache_resource
def _bootstrap():
    """
    Run database and vector-store setup exactly once per Streamlit session.

    @st.cache_resource tells Streamlit: "the return value of this function
    should be created once and reused for the lifetime of the session." So
    even though we call _bootstrap() on every analysis, the body only runs
    on the very first call.

    We return True only so cache_resource has something to cache — the
    real work is the side-effect of init_db()/init_chroma() running.
    """
    init_db()
    init_chroma()
    return True


# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AVE — Website Analyzer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────

def check_auth() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.title("🔍 AVE — Website Analyzer")
    st.caption("SEO intelligence engine for Fort Lauderdale businesses")
    st.divider()

    with st.form("auth_form"):
        pwd = st.text_input("Password", type="password", placeholder="Enter access password")
        submitted = st.form_submit_button("Sign In", use_container_width=True)

    if submitted:
        expected = st.secrets.get("APP_PASSWORD", "")
        if pwd == expected:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    return False


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def validate_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme in ("http", "https") and parsed.netloc)


def score_color(score: int) -> str:
    if score >= 70:
        return "green"
    if score >= 41:
        return "orange"
    return "red"


def score_emoji(score: int) -> str:
    if score >= 70:
        return "🟢"
    if score >= 41:
        return "🟡"
    return "🔴"


def effort_badge(effort: str) -> str:
    return {"low": "🟢 Quick fix", "medium": "🟡 Some effort", "high": "🔴 Heavy lift"}.get(effort, effort)


def checklist_icon(value) -> str:
    if value is True:
        return "✅"
    if value is False:
        return "❌"
    return "⚠️"


def build_markdown_summary(report: dict) -> str:
    score = report["site_intelligence_score"]
    summary = report["summary"]
    lines = [
        f"# AVE Report — {report.get('domain', '')}",
        f"**URL:** {report.get('url', '')}",
        f"**Analyzed:** {report.get('analysis_date', '')[:10]}",
        "",
        f"## Site Intelligence Score: {score['total']}/100 ({score['grade']})",
        "",
        f"| Category | Score | Max |",
        f"|---|---|---|",
        f"| SEO Health | {score['seo_health']} | 30 |",
        f"| Technical Health | {score['technical_health']} | 25 |",
        f"| Business Clarity | {score['business_clarity']} | 25 |",
        f"| Trust Signals | {score['trust_signals']} | 20 |",
        "",
        f"**Business model:** {summary.get('business_model')} ({summary.get('model_confidence')} confidence)",
        f"**Primary promise:** {summary.get('primary_promise')}",
        f"**Biggest opportunity:** {summary.get('biggest_opportunity')}",
        "",
        "## Quick Wins",
    ]
    for i, win in enumerate(report.get("quick_wins", []), 1):
        lines.append(f"{i}. **{win['issue']}**  \n   → {win['fix']}")
    lines += ["", "## Strategic Recommendations"]
    for i, rec in enumerate(report.get("strategic_recommendations", []), 1):
        lines.append(f"{i}. **{rec['issue']}**  \n   → {rec['fix']}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# ANALYSIS RUNNER
# ─────────────────────────────────────────────────────────────

def run_analysis(url: str, depth: str) -> dict:
    """Run the full pipeline with live status updates in the UI."""
    _bootstrap()

    with st.status("Analyzing website...", expanded=True) as status:
        st.write("📄 Fetching and parsing page...")
        st.write("⚡ Measuring Core Web Vitals via PageSpeed Insights (this can take 30+ seconds)...")
        page_report = run_page_inspector(url, depth)

        st.write("🔎 Running SEO audit...")
        seo_report = run_seo_auditor(page_report)

        st.write("🧠 Decoding business signals...")
        business_report = run_business_decoder(page_report)

        st.write("📊 Synthesizing final report...")
        final_report = run_synthesizer(page_report, seo_report, business_report)

        st.write("💾 Saving to database...")
        try:
            save_analysis(final_report)
        except Exception as e:
            st.write(f"⚠️ DB save skipped: {e}")

        st.write("🔗 Indexing for hidden connections...")
        try:
            store_page(final_report)
            store_sections(final_report)
            store_issues(final_report)
        except Exception as e:
            st.write(f"⚠️ Vector index skipped: {e}")

        status.update(label="Analysis complete!", state="complete", expanded=False)

    return final_report


# ─────────────────────────────────────────────────────────────
# REPORT SECTIONS
# ─────────────────────────────────────────────────────────────

def render_score(report: dict) -> None:
    score = report["site_intelligence_score"]
    summary = report["summary"]
    total = score["total"]
    color = score_color(total)

    col_score, col_info = st.columns([1, 2])

    with col_score:
        st.markdown(
            f"""
            <div style="text-align:center; padding: 1rem 0;">
                <div style="font-size: 4rem; font-weight: 800; color: {color}; line-height:1">
                    {total}
                </div>
                <div style="font-size: 1.5rem; color: {color}; font-weight: 600;">/ 100</div>
                <div style="font-size: 2rem; margin-top: 0.25rem;">{score['grade']}</div>
                <div style="font-size: 0.85rem; color: #888; margin-top: 0.25rem;">Site Intelligence Score</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_info:
        st.markdown(f"**{summary.get('business_model', 'Unknown')}** &nbsp;·&nbsp; *{summary.get('model_confidence', '')} confidence*")
        if summary.get("primary_promise"):
            st.markdown(f"_{summary['primary_promise']}_")

        st.markdown("---")
        st.progress(score["seo_health"] / 30, text=f"SEO Health  {score['seo_health']}/30")
        st.progress(score["technical_health"] / 25, text=f"Technical Health  {score['technical_health']}/25")
        st.progress(score["business_clarity"] / 25, text=f"Business Clarity  {score['business_clarity']}/25")
        st.progress(score["trust_signals"] / 20, text=f"Trust Signals  {score['trust_signals']}/20")


def render_quick_wins(report: dict) -> None:
    wins = report.get("quick_wins", [])
    if not wins:
        st.info("No quick wins identified.")
        return

    for win in wins:
        with st.container(border=True):
            col_badge, col_text = st.columns([1, 5])
            with col_badge:
                st.markdown(effort_badge(win.get("effort", "low")))
            with col_text:
                st.markdown(f"**{win['issue']}**")
                st.markdown(f"→ {win['fix']}")


def render_strategic_recs(report: dict) -> None:
    recs = report.get("strategic_recommendations", [])
    if not recs:
        st.info("No high-effort strategic recommendations at this time.")
        return

    for rec in recs:
        with st.container(border=True):
            col_badge, col_text = st.columns([1, 5])
            with col_badge:
                st.markdown(effort_badge(rec.get("effort", "high")))
            with col_text:
                st.markdown(f"**{rec['issue']}**")
                st.markdown(f"→ {rec['fix']}")


def render_hidden_connections(report: dict) -> None:
    url = report.get("url", "")
    if not url:
        return

    st.markdown("### Hidden Connections — What Similar Sites Are Doing Better")

    # ── Similar sites ──
    try:
        similar = find_similar_sites(url, n=5)
    except Exception as e:
        similar = []
        st.warning(f"Similar sites lookup failed: {e}")

    # Check corpus size to show gentle message if thin
    corpus_count = 0
    try:
        from scripts.vector_store import _get_chroma
        init_chroma()
        corpus_count = _get_chroma().get_or_create_collection("pages").count()
    except Exception as e:
        st.warning(f"Corpus check failed: {e}")

    if corpus_count < 10:
        st.info(
            "The comparison corpus is still being built. "
            "Run `python scripts/seed.py` to populate it with local business benchmarks."
        )
        return

    if similar:
        st.markdown("**Top similar sites in the corpus**")
        cols = st.columns(min(3, len(similar)))
        for i, site in enumerate(similar[:3]):
            with cols[i]:
                delta = site.get("score_delta", 0)
                delta_str = f"+{delta}" if delta > 0 else str(delta)
                delta_color = "green" if delta > 0 else ("red" if delta < 0 else "gray")
                st.markdown(
                    f"""
                    <div style="border:1px solid #ddd; border-radius:8px; padding:0.75rem; text-align:center;">
                        <div style="font-weight:600; font-size:0.85rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                            {site.get('domain', '')}
                        </div>
                        <div style="font-size:0.75rem; color:#888; margin:0.15rem 0;">
                            {site.get('category', '').replace('_', ' ').title()}
                        </div>
                        <div style="font-size:1.5rem; font-weight:700;">{site.get('score', '—')}</div>
                        <div style="font-size:0.8rem; color:{delta_color};">{delta_str} vs. you</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    else:
        st.info("No similar sites found yet — analyze more URLs to build comparisons.")

    # ── Content gaps ──
    st.markdown("")
    st.markdown("**Topics top-performing sites cover that you don't**")
    try:
        gaps = find_content_gaps(url)
    except Exception:
        gaps = []

    if gaps:
        for gap in gaps:
            st.markdown(f"- {gap}")
    else:
        st.caption("No content gaps detected — your page covers similar topics as comparable sites.")

    # ── Solved problems ──
    quick_wins = report.get("quick_wins", [])
    if quick_wins:
        st.markdown("")
        st.markdown("**Sites that fixed your biggest issue**")
        top_issue = quick_wins[0].get("issue", "")
        try:
            solved = find_solved_problems(top_issue)
        except Exception:
            solved = []

        if solved:
            for item in solved:
                with st.container(border=True):
                    col_a, col_b = st.columns([1, 3])
                    with col_a:
                        st.markdown(f"**{item.get('domain', '')}**")
                        st.markdown(f"Score: {item.get('score', '—')}")
                    with col_b:
                        st.markdown(f"*Issue:* {item.get('issue', '')}")
                        if item.get("fix"):
                            st.markdown(f"*What they did:* {item['fix']}")
        else:
            st.caption("No solved-problem examples found yet.")


def render_detail_sections(report: dict) -> None:
    seo = report.get("seo_audit", {})
    business = report.get("business_decoder", {})
    page = report.get("page_report", {})

    # ── Page Inspector ──
    with st.expander("Page Inspector findings", expanded=False):
        meta = page.get("meta", {})
        content = page.get("content", {})
        tech = page.get("tech", {})

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Meta**")
            title = meta.get("title", {})
            st.markdown(f"- Title: `{title.get('text', '—')[:60]}` ({title.get('length', 0)} chars)")
            desc = meta.get("description", {})
            st.markdown(f"- Description: {desc.get('length', 0)} chars")
            st.markdown(f"- Canonical: {meta.get('canonical') or '—'}")
            st.markdown(f"- Viewport: {checklist_icon(meta.get('viewport', {}).get('correct'))}")

            st.markdown("**Content**")
            headings = content.get("headings", {})
            h1s = headings.get("h1", {}).get("texts", [])
            st.markdown(f"- H1: {h1s[0][:50] if h1s else '—'}")
            st.markdown(f"- H2 count: {headings.get('h2', {}).get('count', 0)}")
            st.markdown(f"- Word count: ~{content.get('word_count', 0)}")

        with col2:
            st.markdown("**Technology**")
            st.markdown(f"- CMS: {tech.get('cms', 'Unknown')}")
            st.markdown(f"- Framework: {tech.get('framework') or 'None'}")
            analytics = tech.get("analytics", [])
            st.markdown(f"- Analytics: {', '.join(analytics) if analytics else 'None detected'}")
            mkt = tech.get("marketing_tools", [])
            st.markdown(f"- Marketing tools: {', '.join(mkt) if mkt else 'None detected'}")

            st.markdown("**Trust signals**")
            trust = page.get("trust", {})
            st.markdown(f"- HTTPS: {checklist_icon(trust.get('https'))}")
            st.markdown(f"- Phone visible: {checklist_icon(trust.get('phone_visible'))}")
            st.markdown(f"- Contact link: {checklist_icon(trust.get('contact_link'))}")
            st.markdown(f"- Social proof: {checklist_icon(trust.get('has_social_proof'))}")

    # ── SEO Audit ──
    with st.expander("SEO Audit — E-E-A-T, Core Web Vitals, technical checklist", expanded=False):
        eeat = seo.get("eeat", {})
        cwv = seo.get("core_web_vitals", {})
        technical = seo.get("technical_checklist", {})

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**E-E-A-T scores (0–10 each)**")
            for pillar in ("experience", "expertise", "authoritativeness", "trustworthiness"):
                val = eeat.get(pillar, 0)
                bar = "█" * val + "░" * (10 - val)
                st.markdown(f"- {pillar.title()}: `{bar}` {val}/10")

            st.markdown("**Core Web Vitals**")
            for metric, data in cwv.items():
                verdict = data.get("verdict", "Unknown")
                icon = {"Good": "✅", "Needs Improvement": "⚠️", "Poor": "❌"}.get(verdict, "❓")
                st.markdown(f"- {metric.upper()}: {icon} {verdict}")

        with col2:
            st.markdown("**Technical checklist**")
            critical = technical.get("critical", {})
            important = technical.get("important", {})
            nice = technical.get("nice_to_have", {})

            for label, checks in [("Critical", critical), ("Important", important), ("Nice to have", nice)]:
                st.markdown(f"*{label}*")
                for key, val in checks.items():
                    pretty = key.replace("_", " ").replace("has ", "").title()
                    st.markdown(f"  {checklist_icon(val)} {pretty}")

    # ── Business Decoder ──
    with st.expander("Business Decoder — model, audience, funnel, positioning", expanded=False):
        bm = business.get("business_model", {})
        audience = business.get("audience", {})
        funnel = business.get("funnel", {})
        positioning = business.get("positioning", {})

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Business model**")
            st.markdown(f"- Model: **{bm.get('primary', 'Unknown')}** ({bm.get('confidence', '—')} confidence)")

            st.markdown("**Audience signals**")
            st.markdown(f"- Language: {audience.get('language_complexity', '—')}")
            st.markdown(f"- Price sensitivity: {audience.get('price_sensitivity', '—')}")
            st.markdown(f"- Geographic focus: {audience.get('geographic_focus', '—')}")
            st.markdown(f"- Company size: {audience.get('company_size_target', '—')}")

        with col2:
            st.markdown("**Conversion funnel**")
            strength_icon = {"strong": "💪", "present": "✅", "thin": "⚠️", "missing": "❌"}
            for stage, data in funnel.items():
                strength = data.get("strength", "missing")
                icon = strength_icon.get(strength, "")
                st.markdown(f"- {stage.title()}: {icon} {strength}")

            st.markdown("**Positioning**")
            promise = positioning.get("primary_promise", "—")
            st.markdown(f"- Promise: _{promise}_")
            differentiators = positioning.get("differentiators", [])
            if differentiators:
                st.markdown(f"- Differentiators: {', '.join(differentiators[:3])}")
            tone = positioning.get("brand_tone", "")
            if tone:
                st.markdown(f"- Brand tone: {tone}")


def render_export(report: dict) -> None:
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="⬇️ Download full report (JSON)",
            data=json.dumps(report, indent=2, default=str),
            file_name=f"{report.get('domain', 'report').replace('.', '_')}_report.json",
            mime="application/json",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            label="⬇️ Download summary (Markdown)",
            data=build_markdown_summary(report),
            file_name=f"{report.get('domain', 'report').replace('.', '_')}_summary.md",
            mime="text/markdown",
            use_container_width=True,
        )


def render_report(report: dict) -> None:
    domain = report.get("domain", report.get("url", ""))
    st.markdown(f"### {domain}")
    st.caption(report.get("url", ""))

    render_score(report)
    st.divider()

    st.markdown("#### Quick Wins")
    render_quick_wins(report)

    st.markdown("#### Strategic Recommendations")
    render_strategic_recs(report)

    st.divider()
    render_hidden_connections(report)

    st.divider()
    render_detail_sections(report)

    st.divider()
    st.markdown("#### Export")
    render_export(report)


# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### Analysis History")

        try:
            init_db()
            history = get_all_analyses()
        except Exception:
            history = []

        if not history:
            st.caption("No analyses yet. Analyze a URL to get started.")
            return

        for row in history[:50]:
            score = row.get("site_intelligence_score", 0) or 0
            emoji = score_emoji(score)
            domain = row.get("domain", row.get("url", "—"))
            date = (row.get("analysis_date") or "")[:10]
            label = f"{emoji} {domain}  **{score}**"

            if st.button(label, key=f"hist_{row['id']}", use_container_width=True, help=f"{date}"):
                cached = get_analysis(row["url"])
                if cached:
                    st.session_state.report = cached
                    st.session_state.loaded_from_history = True
                    st.rerun()


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main() -> None:
    if not check_auth():
        st.stop()

    # ── Session state defaults ──
    if "report" not in st.session_state:
        st.session_state.report = None
    if "loaded_from_history" not in st.session_state:
        st.session_state.loaded_from_history = False

    render_sidebar()

    # ── Header ──
    st.title("🔍 AVE — Website Analyzer")
    st.caption("Enter any URL to get an SEO, technical, and business intelligence report.")

    # ── Input form ──
    with st.form("analyze_form"):
        url_input = st.text_input(
            "Website URL",
            placeholder="https://example.com",
            help="Include the full URL with https://",
        )
        depth_choice = st.radio(
            "Analysis depth",
            options=["Surface (fast, ~15s)", "Deep (thorough, ~60s)"],
            horizontal=True,
            help="Surface = homepage only. Deep = homepage + sitemap + subpages.",
        )
        submitted = st.form_submit_button("Analyze", use_container_width=True, type="primary")

    # ── Validate and run ──
    if submitted:
        url = url_input.strip()
        if not url:
            st.error("Please enter a URL.")
        elif not validate_url(url):
            st.error("Invalid URL. Include the full address, e.g. `https://example.com`")
        else:
            depth = "deep" if "Deep" in depth_choice else "surface"
            st.session_state.loaded_from_history = False
            try:
                st.session_state.report = run_analysis(url, depth)
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                import traceback
                with st.expander("Error details"):
                    st.code(traceback.format_exc())

    # ── Display report ──
    if st.session_state.report:
        st.divider()
        if st.session_state.loaded_from_history:
            st.info("Showing cached report from history.")
        render_report(st.session_state.report)


if __name__ == "__main__":
    main()
