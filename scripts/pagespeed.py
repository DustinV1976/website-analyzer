"""
PageSpeed Insights
==================

Fetches real Core Web Vitals data from Google's PageSpeed Insights API (PSI).

There are TWO data sources inside every PSI response:

  1. Field data (CrUX) — real users' actual experiences over the last 28 days.
     This is what Google ACTUALLY uses for ranking. Only available when the
     site has enough Chrome traffic to be in the public CrUX dataset.

  2. Lab data (Lighthouse) — a synthetic test run from Google's servers.
     Available for every site. Less accurate than field data, but always there.

We prefer field data when available, and fall back to lab data when not.

This module follows the same "always return a dict, never raise" convention
used by scripts/fetcher.py — so if the API key is missing, the network fails,
or the site isn't in CrUX, the caller still gets back a well-shaped dict
(with None values), and the SEO auditor renders "Unknown" — exactly the
behavior we had before this module existed.

Requires PAGESPEED_API_KEY in the .env file. Get one for free at:
  https://developers.google.com/speed/docs/insights/v5/get-started
"""

import os
from typing import Any
import requests
from dotenv import load_dotenv


# Google's PageSpeed Insights v5 endpoint
PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# PSI calls are SLOW — 15 to 30 seconds is normal, occasionally up to 60s for
# heavy sites. We give it plenty of room rather than wasting the wait so far.
PSI_TIMEOUT = 60

# Default shape we return whenever anything goes wrong. Keeping every caller's
# downstream code simple — they can always assume the same keys.
# The auditor only reads lcp / cls / inp / performance_category — `source`
# and `error` are extra debugging info that get embedded in the report.
EMPTY_RESULT = {
    "lcp": None,
    "cls": None,
    "inp": None,
    "performance_category": None,
    "source": None,   # "field" | "lab" | None
    "error": None,
}


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _safe_get(dct: dict, *keys: str, default: Any = None) -> Any:
    """
    Walk a nested dict safely. PSI responses have deep paths like
    response['lighthouseResult']['audits']['largest-contentful-paint']['numericValue']
    and any one of those keys may be missing on any given response.

    Returns `default` (None) the moment any key is absent.
    """
    cur: Any = dct
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


# ─────────────────────────────────────────────────────────────
# EXTRACTORS — one for each data source PSI provides
# ─────────────────────────────────────────────────────────────

def _extract_field_data(psi_json: dict):
    """
    Pull LCP / CLS / INP from the CrUX field-data section
    (loadingExperience.metrics).

    Unit conversions:
      LCP percentile → MILLISECONDS in the response. Auditor wants SECONDS.
      CLS percentile → multiplied by 100 in the response (so "5" means 0.05).
                       Auditor wants the raw decimal.
      INP percentile → MILLISECONDS in the response. Auditor wants ms. (no conversion)

    Returns None if there's no field data at all (low-traffic sites that
    aren't in the public CrUX dataset yet).
    """
    metrics = _safe_get(psi_json, "loadingExperience", "metrics")
    if not metrics:
        return None

    lcp_ms = _safe_get(metrics, "LARGEST_CONTENTFUL_PAINT_MS", "percentile")
    cls_x100 = _safe_get(metrics, "CUMULATIVE_LAYOUT_SHIFT_SCORE", "percentile")
    inp_ms = _safe_get(metrics, "INTERACTION_TO_NEXT_PAINT", "percentile")

    # If none of the three are present, treat it as "no field data"
    if lcp_ms is None and cls_x100 is None and inp_ms is None:
        return None

    return {
        "lcp": round(lcp_ms / 1000, 2) if lcp_ms is not None else None,
        "cls": round(cls_x100 / 100, 3) if cls_x100 is not None else None,
        "inp": inp_ms,  # already ms — matches the auditor's threshold units
    }


def _extract_lab_data(psi_json: dict):
    """
    Pull LCP / CLS / INP from the Lighthouse lab-data section
    (lighthouseResult.audits).

    Unit conversions:
      largest-contentful-paint.numericValue   → MILLISECONDS → seconds
      cumulative-layout-shift.numericValue    → already a raw decimal (0.05)
      interaction-to-next-paint.numericValue  → MILLISECONDS → keep as ms

    Lab data can't simulate user interaction the way real users do, so INP
    is often missing from the lab section — that's expected, not a bug.
    """
    audits = _safe_get(psi_json, "lighthouseResult", "audits")
    if not audits:
        return None

    lcp_ms = _safe_get(audits, "largest-contentful-paint", "numericValue")
    cls = _safe_get(audits, "cumulative-layout-shift", "numericValue")
    inp_ms = _safe_get(audits, "interaction-to-next-paint", "numericValue")

    if lcp_ms is None and cls is None and inp_ms is None:
        return None

    return {
        "lcp": round(lcp_ms / 1000, 2) if lcp_ms is not None else None,
        "cls": round(cls, 3) if cls is not None else None,
        "inp": round(inp_ms) if inp_ms is not None else None,
    }


def _extract_performance_category(psi_json: dict):
    """
    Overall Lighthouse performance score (0.0–1.0) → human-readable bucket.
    Matches Google's color buckets in the PSI web UI.
    """
    score = _safe_get(
        psi_json, "lighthouseResult", "categories", "performance", "score"
    )
    if score is None:
        return None
    if score >= 0.9:
        return "Fast"
    if score >= 0.5:
        return "Average"
    return "Slow"


# ─────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────────

def get_pagespeed(
    url: str,
    api_key: str | None = None,
    strategy: str = "mobile",
) -> dict:
    """
    Fetch Core Web Vitals from Google's PageSpeed Insights API.

    Args:
        url:       URL to analyze.
        api_key:   PSI API key. If None, reads PAGESPEED_API_KEY from .env.
        strategy:  "mobile" (default) or "desktop". Use "mobile" — Google
                   uses mobile-first indexing for rankings, so mobile CWV
                   are what actually impact SEO.

    Returns:
        A dict shaped like EMPTY_RESULT. Every key is always present.
        When any step fails (no key, timeout, no data, etc.) the metric
        values are None and the auditor renders "Unknown" — same fallback
        behavior we had before this function existed.
    """
    # ── Resolve the API key ──
    if api_key is None:
        load_dotenv()  # safe to call even if there's no .env file
        api_key = os.getenv("PAGESPEED_API_KEY")

    if not api_key:
        # Not an error — just a config choice. Caller can disable PSI by
        # leaving PAGESPEED_API_KEY out of .env.
        return {**EMPTY_RESULT, "error": "PAGESPEED_API_KEY not set"}

    # ── Call the PSI endpoint ──
    params = {
        "url": url,
        "key": api_key,
        "strategy": strategy,
        "category": "performance",
    }
    try:
        response = requests.get(PSI_ENDPOINT, params=params, timeout=PSI_TIMEOUT)
        if response.status_code != 200:
            return {
                **EMPTY_RESULT,
                "error": f"PSI returned HTTP {response.status_code}",
            }
        data = response.json()
    except requests.exceptions.Timeout:
        return {**EMPTY_RESULT, "error": "PSI request timed out"}
    except requests.exceptions.RequestException as e:
        return {**EMPTY_RESULT, "error": f"PSI request failed: {e}"}
    except ValueError:
        # response.json() raises ValueError on non-JSON bodies (e.g. HTML error pages)
        return {**EMPTY_RESULT, "error": "PSI returned non-JSON response"}

    # ── Prefer field data (CrUX, real users) over lab data (Lighthouse) ──
    field = _extract_field_data(data)
    lab = _extract_lab_data(data)

    if field:
        metrics, source = field, "field"
    elif lab:
        metrics, source = lab, "lab"
    else:
        # PSI replied successfully but had no usable metrics. We can still
        # surface the overall performance category from the Lighthouse score.
        return {
            **EMPTY_RESULT,
            "performance_category": _extract_performance_category(data),
            "error": "No CWV data returned",
        }

    return {
        "lcp": metrics["lcp"],
        "cls": metrics["cls"],
        "inp": metrics["inp"],
        "performance_category": _extract_performance_category(data),
        "source": source,
        "error": None,
    }


# ─────────────────────────────────────────────────────────────
# QUICK TEST
# Run with:  python scripts/pagespeed.py <url>
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    print(f"Fetching PageSpeed Insights for {test_url}...")
    print("(this can take 15-30 seconds — the API itself is slow)\n")
    result = get_pagespeed(test_url)
    print(json.dumps(result, indent=2))