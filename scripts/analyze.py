"""
CLI Entry Point — Website Analyzer
===================================

Orchestrates all four agents in sequence and produces a final report:

  Page Inspector ──► SEO Auditor ──┐
                  └► Business      ├──► Synthesizer ──► FINAL_REPORT
                     Decoder ──────┘

Usage:
    python scripts/analyze.py <url> [--depth surface|deep] [--quiet]

Examples:
    python scripts/analyze.py https://example.com
    python scripts/analyze.py https://joesplumbing.com --depth deep
    python scripts/analyze.py https://example.com --quiet  # only print summary
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


# ─────────────────────────────────────────────────────────────
# IMPORT PLUMBING
# Adds the project root to Python's import path so `from scripts.agents...`
# works whether you run this as a script or import it as a module.
# Beginner tip: this is the one place we need this kind of magic — the
# rest of the codebase can just write plain `from scripts.X import ...`.
# ─────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.agents.page_inspector import run as run_page_inspector
from scripts.agents.seo_auditor import run as run_seo_auditor
from scripts.agents.business_decoder import run as run_business_decoder
from scripts.agents.synthesizer import run as run_synthesizer


# ─────────────────────────────────────────────────────────────
# PIPELINE
# ─────────────────────────────────────────────────────────────

def analyze(url: str, depth: str = "surface", verbose: bool = True) -> dict:
    """
    Run the full 4-agent pipeline on a URL.

    Args:
        url:     URL to analyze (must include scheme, e.g. https://...)
        depth:   "surface" (fast) or "deep" (includes sitemap + subpages)
        verbose: print progress messages between steps

    Returns:
        FINAL_REPORT dict from the Synthesizer
    """
    if verbose: print(f"🔍 Analyzing {url}  (depth: {depth})")

    if verbose: print("  📄 Fetching and parsing page...")
    page_report = run_page_inspector(url, depth)

    if verbose: print("  🔎 Running SEO audit...")
    seo_report = run_seo_auditor(page_report)

    if verbose: print("  🧠 Decoding business signals...")
    business_report = run_business_decoder(page_report)

    if verbose: print("  📊 Synthesizing final report...")
    final_report = run_synthesizer(page_report, seo_report, business_report)

    return final_report


# ─────────────────────────────────────────────────────────────
# OUTPUT HELPERS
# ─────────────────────────────────────────────────────────────

def save_report(final_report: dict, output_dir: str = "data/reports") -> Path:
    """Save the FINAL_REPORT as a timestamped JSON file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Build a filesystem-safe filename: domain_YYYYMMDD_HHMMSS.json
    domain = (final_report.get("domain") or "unknown").replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = output_path / f"{domain}_{timestamp}.json"

    # default=str lets datetime objects serialize cleanly
    with open(file_path, "w") as f:
        json.dump(final_report, f, indent=2, default=str)

    return file_path


def print_summary(final_report: dict) -> None:
    """Print a clean, scannable summary of the analysis to stdout."""
    score = final_report["site_intelligence_score"]
    summary = final_report["summary"]

    print()
    print("═" * 50)
    print(f" SITE INTELLIGENCE SCORE: {score['total']}/100  ({score['grade']})")
    print("═" * 50)
    print(f"  SEO Health:        {score['seo_health']:>2d}/30")
    print(f"  Technical Health:  {score['technical_health']:>2d}/25")
    print(f"  Business Clarity:  {score['business_clarity']:>2d}/25")
    print(f"  Trust Signals:     {score['trust_signals']:>2d}/20")
    print("═" * 50)

    print(f"\n  Business model:        {summary['business_model']} "
          f"({summary['model_confidence']} confidence)")
    print(f"  Primary promise:       {summary['primary_promise']}")
    print(f"  Biggest opportunity:   {summary['biggest_opportunity']}")

    if final_report.get("quick_wins"):
        print("\n── QUICK WINS ──")
        for i, win in enumerate(final_report["quick_wins"], 1):
            print(f"  {i}. {win['issue']}")
            print(f"     → {win['fix']}")

    if final_report.get("strategic_recommendations"):
        print("\n── STRATEGIC RECOMMENDATIONS ──")
        for i, rec in enumerate(final_report["strategic_recommendations"], 1):
            print(f"  {i}. {rec['issue']}")
            print(f"     → {rec['fix']}")


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def validate_url(url: str) -> bool:
    """Make sure the URL has both a scheme and a domain."""
    parsed = urlparse(url)
    return bool(parsed.scheme and parsed.netloc)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a website's SEO, technical health, and business positioning.",
        epilog="Example: python scripts/analyze.py https://example.com --depth deep",
    )
    parser.add_argument("url", help="Full URL to analyze (must include https://)")
    parser.add_argument(
        "--depth",
        choices=["surface", "deep"],
        default="surface",
        help="surface = homepage only (~15s) | deep = sitemap + subpages (~60s)",
    )
    parser.add_argument(
        "--output-dir",
        default="data/reports",
        help="Where to save the JSON report (default: data/reports)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress progress messages — only print the final summary",
    )

    args = parser.parse_args()

    # ── Validate the URL before doing any work ──
    if not validate_url(args.url):
        print(f"❌ Invalid URL: {args.url}")
        print("   Make sure to include the scheme, e.g. https://example.com")
        sys.exit(1)

    # ── Run the pipeline (catch any errors gracefully) ──
    try:
        final_report = analyze(args.url, depth=args.depth, verbose=not args.quiet)
    except KeyboardInterrupt:
        print("\n⚠️  Analysis cancelled by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        if not args.quiet:
            # Print traceback for debugging when not in quiet mode
            import traceback
            traceback.print_exc()
        sys.exit(1)

    # ── Print summary and save report ──
    print_summary(final_report)
    saved_path = save_report(final_report, args.output_dir)
    print(f"\n💾 Full report saved to: {saved_path}")


if __name__ == "__main__":
    main()