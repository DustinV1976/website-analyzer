"""
Corpus Seed Script — Phase 3
=============================

Batch-analyzes Fort Lauderdale URLs and stores them with category + location tags
so the Hidden Connections queries have relevant local comparisons.

Usage:
    python scripts/seed.py [--dry-run]

Options:
    --dry-run   Print URLs that would be analyzed without running them
"""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analyze import analyze

LOCATION = "Fort Lauderdale FL"
PAUSE_SECONDS = 2

CORPUS = {
    "marine": [
        "https://www.bradfordmarine.com",
        "https://www.denisonyachtsales.com",
        "https://iyc.com",
        "https://www.fraseryachts.com",
        "https://www.topshotfishing.com",
        "https://www.fishheadquarters.com",
        "https://flatbottomcharters.com",
    ],
    "restaurants": [
        "https://www.coconutsfortlauderdale.com",
        "https://boatyard.restaurant",
        "https://www.shooterswaterfront.com",
        "https://thehouseontheriver.com",
        "https://casablancacafeonline.com",
        "https://steak954.com",
        "https://www.southportrawbar.com",
    ],
    "real_estate": [
        "https://www.bythesearealty.com",
        "https://dangelorealty.com",
        "https://timelmes.com",
        "https://bergercommercial.com",
        "https://www.metrofla.com",
        "https://www.mayfairpropertymanagement.com",
        "https://www.cruiseproperty.com",
    ],
    "healthcare": [
        "https://www.goldcoastdentalcenter.com",
        "https://dentalteamfl.com",
        "https://www.coralridgesmile.com",
        "https://www.fortlauderdaleperio.com",
        "https://www.fienodontics.com",
        "https://urgentcareflauderdale.com",
        "https://www.browardmedicalurgentcare.com",
    ],
    "home_services": [
        "https://www.qualityac.com",
        "https://www.hivacair.com",
        "https://paradiseplumbingandac.com",
        "https://dascorplumbing.com",
        "https://www.abcroofingcorp.com",
        "https://www.lawnservicefortlauderdale.com",
        "https://www.nativepestmanagement.com",
    ],
    "hotels": [
        "https://www.pelicanbeach.com",
        "https://www.boceanresort.com",
        "https://www.oceanskyresort.com",
        "https://www.shorebreakfortlauderdale.com",
        "https://www.thenorthbeachhotel.com",
        "https://www.oasishotelftl.com",
        "https://www.suntowerhotelsuites.com",
    ],
    "law_firms": [
        "https://browardlegal.com",
        "https://stoklaw.com",
        "https://www.valdeslawfirmpa.com",
        "https://www.ftlinjurylaw.com",
        "https://winstonlaw.com",
        "https://kelleyuustal.com",
        "https://www.flafirm.com",
    ],
    "beauty_wellness": [
        "https://bewellmedspa.com",
        "https://thefortlauderdalemedspa.com",
        "https://lumierebyadriana.com",
        "https://casbahspa.com",
        "https://www.balticbeautycentre.com",
        "https://www.seraphinespa.com",
        "https://www.sqlptpilates.com",
    ],
}


def main():
    parser = argparse.ArgumentParser(description="Seed the Fort Lauderdale corpus")
    parser.add_argument("--dry-run", action="store_true", help="Print URLs without analyzing")
    args = parser.parse_args()

    total = sum(len(v) for v in CORPUS.values())
    succeeded, failed = 0, []

    print(f"{'DRY RUN — ' if args.dry_run else ''}Seeding {total} Fort Lauderdale URLs\n")

    for category, urls in CORPUS.items():
        print(f"── {category.upper().replace('_', ' ')} ({len(urls)} sites) ──")
        for url in urls:
            if args.dry_run:
                print(f"  {url}")
                continue

            try:
                report = analyze(url, depth="surface", verbose=False, location=LOCATION)
                # Re-upsert the page vector with category + is_seed tags
                # (analyze() only has location; seed needs category too)
                from scripts.vector_store import store_page
                store_page(report, category=category, location=LOCATION, is_seed=True)
                score = report["site_intelligence_score"]["total"]
                model = report["summary"]["business_model"]
                print(f"  ✓ {url:<55}  score={score:>3}  {model}")
                succeeded += 1
            except Exception as e:
                print(f"  ✗ {url:<55}  ERROR: {e}")
                failed.append((url, str(e)))

            time.sleep(PAUSE_SECONDS)

        print()

    if not args.dry_run:
        print(f"Done — {succeeded} succeeded, {len(failed)} failed")
        if failed:
            print("\nFailed URLs:")
            for url, err in failed:
                print(f"  {url}  →  {err}")


if __name__ == "__main__":
    main()
