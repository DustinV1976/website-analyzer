# Website Analyzer — v1 Product TODO

**Goal:** A Streamlit web app for SEO professionals that analyzes any URL and surfaces
hidden connections using a vector database pre-seeded with Fort Lauderdale local business sites.

**Target user:** SEO professional
**Stack:** Python · Streamlit · SQLite · ChromaDB · OpenAI Embeddings · BeautifulSoup · Playwright
**Hosting:** Streamlit Community Cloud (free, public HTTPS URL)

---

## Before You Start — API Keys Needed

Get these before writing any code:

| Key | Where to get it | Used for |
|---|---|---|
| `OPENAI_API_KEY` | platform.openai.com | Embeddings (text-embedding-3-small) |
| `PAGESPEED_API_KEY` | console.developers.google.com | Real Core Web Vitals data |
| `APP_PASSWORD` | You choose it | Streamlit password gate |

Store all three in a `.env` file. Never commit that file to GitHub.

---

## Phase 0 — Project Setup

- [ ] Create GitHub repo: `website-analyzer`
- [x] Set up Python virtual environment: `python -m venv venv`
- [ ] Create `requirements.txt` with:
  - `streamlit`, `requests`, `beautifulsoup4`, `lxml`
  - `playwright`, `chromadb`, `openai`
  - `textstat`, `python-dotenv`, `tqdm`
- [x] Run `pip install requests beautifulsoup4 lxml textstat`
- [ ] Run `playwright install chromium`
- [ ] Create `.env` file with the three keys above
- [ ] Add `.env` to `.gitignore`
- [x] Create this folder structure:

```
website-analyzer/
├── app.py                        # Streamlit entry point (Phase 4)
├── scripts/
│   ├── __init__.py               # ← required, keep empty
│   ├── analyze.py                # CLI orchestrator ✅
│   ├── fetcher.py                # HTTP + Playwright fetcher ✅
│   ├── parsers.py                # HTML extraction functions ✅
│   ├── seed.py                   # Pre-seed corpus batch script (Phase 3)
│   └── agents/
│       ├── __init__.py           # ← required, keep empty
│       ├── page_inspector.py     # ✅
│       ├── seo_auditor.py        # ✅
│       ├── business_decoder.py   # ✅
│       └── synthesizer.py        # ✅
├── data/
│   ├── analyses.db               # SQLite (auto-created, Phase 2)
│   ├── chroma/                   # ChromaDB storage (auto-created, Phase 2)
│   └── reports/                  # Saved JSON reports ✅ (auto-created on first run)
├── corpus/
│   └── fort_lauderdale_urls.txt  # Pre-seed URL list (Phase 3)
├── .streamlit/
│   └── secrets.toml              # Streamlit Cloud config (Phase 5)
├── requirements.txt
├── .env
└── README.md
```

---

## Phase 1 — Python Analysis Engine ✅ COMPLETE

> **Design principle:** The core analysis engine works on ANY website, ANY location,
> ANY business type. Fort Lauderdale data belongs only in the seed corpus (Phase 3),
> not in any analysis logic.

### 1a. Data Fetcher (`scripts/fetcher.py`) ✅

- [x] `fetch_page(url)` → returns `{ html, headers, status_code, final_url }`
  - Handles redirects, retries (3x), and timeouts (10s)
  - Follows redirects and records the final landing URL
- [x] `detect_spa(html)` → returns `True` if page looks JS-rendered
  - Checks for: `__NEXT_DATA__`, `<div id="root">`, `ng-version`, `data-reactroot`
  - Checks if visible text word count is under 100
- [x] `fetch_with_playwright(url)` → Playwright fallback for SPA sites
  - Waits for `networkidle` before returning HTML
- [x] `smart_fetch(url)` → calls `fetch_page`, falls back to Playwright if SPA detected
- [x] All errors handled gracefully: always returns a dict, never raises an uncaught exception

### 1b. HTML Parsers (`scripts/parsers.py`) ✅

**Meta signals:**
- [x] `parse_title(soup)` → text, character length, passes 50–60 char check
- [x] `parse_meta_description(soup)` → text, length, passes 150–160 char check
- [x] `parse_canonical(soup)` → URL string or None
- [x] `parse_open_graph(soup)` → dict of all og: tags
- [x] `parse_twitter_card(soup)` → present? card type?
- [x] `parse_viewport(soup)` → correctly set for mobile?

**Content structure:**
- [x] `parse_headings(soup)` → dict with H1/H2/H3 lists and counts
- [x] `check_h1(headings)` → exactly one? count?
- [x] `estimate_word_count(soup)` → strips nav/footer/scripts, counts body words
- [x] `find_faq_section(soup)` → FAQ present? (signals rich snippet opportunity)
- [x] `parse_author_info(soup)` → name if present (3 fallback strategies)
- [x] `parse_dates(soup)` → published date, last modified date

**Schema and structured data:**
- [x] `parse_schema(soup)` → all JSON-LD blocks with their @type values
- [x] `check_local_business_schema(schema_list)` → LocalBusiness present? Has geo? Has hours?

**Links:**
- [x] `parse_links(soup, base_url)` → internal count, external count, anchor texts
- [x] `flag_bad_anchor_text(anchors)` → flags "click here", "read more", "here"

**Trust and conversion:**
- [x] `parse_trust_signals(soup)` → contact, about, privacy links, phone, email, social proof
- [x] `parse_cta(soup)` → primary CTA text and tag

**Tech fingerprinting:**
- [x] `detect_cms(html)` → WordPress, Shopify, Squarespace, Wix, Webflow, or Unknown
- [x] `detect_framework(html)` → React, Next.js, Vue, Angular, or None
- [x] `detect_analytics(html)` → GA4, GTM, Hotjar, Segment, Mixpanel, FullStory, Clarity
- [x] `detect_marketing_tools(html)` → HubSpot, Intercom, Drift, Klaviyo, Mailchimp, Calendly

**Readability:**
- [x] `score_readability(text)` → Flesch-Kincaid grade level via `textstat`
  - Maps to audience: < 9 = general consumer, 9–11 = educated, 12+ = specialist

### 1c. Supporting File Fetchers ✅

- [x] `fetch_robots_txt(domain)` → disallowed paths, sitemap URL pointer, found flag
- [x] `fetch_sitemap(domain)` → URL list, page count, content categories from URL patterns
- [x] `fetch_subpage(domain, path)` → fetches /about, /contact, /services, /reviews
- [x] All return gracefully with `found: False` if file doesn't exist

### 1d. Real Data Sources ⚠️ STUBBED — wire up in v1.1

**Google PageSpeed Insights:**
- [ ] `get_pagespeed(url, api_key)` → real LCP, CLS, INP scores + performance category
  - Requires `PAGESPEED_API_KEY` in `.env`
  - LCP: Good < 2.5s, Poor > 4.0s
  - CLS: Good < 0.1, Poor > 0.25
  - INP: Good < 200ms, Poor > 500ms
- **Current state:** Returns `None` for all metrics. Auditor shows "Unknown" for CWV — harmless but incomplete.

**Security headers:**
- [ ] `check_security_headers(response_headers)` → HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy
- [ ] Return score 0–5 (one point per header present)
- **Current state:** Returns score 0, empty list. Add to `page_inspector.py` once built.

**SSL certificate:**
- [ ] `check_ssl(domain)` → expiry date, days remaining, issuer, TLS version
- [ ] Flag if expiry is within 30 days
- **Current state:** Returns `None`. Add to `page_inspector.py` once built.

### 1e. Agent 1 — Page Inspector (`scripts/agents/page_inspector.py`) ✅

- [x] `run(url, depth)` orchestrates the full fetch sequence:
  1. `smart_fetch(url)` → main page
  2. `fetch_robots_txt(domain)`
  3. If depth == `deep`: `fetch_sitemap(domain)` + `/about`, `/contact`, `/services`, `/reviews`
- [x] Calls all parsers on fetched HTML
- [x] Returns `PAGE_INSPECTOR_REPORT` dict with all extracted signals
- [ ] Wire up `get_pagespeed`, `check_security_headers`, `check_ssl` when built (1d above)

### 1f. Agent 2 — SEO Auditor (`scripts/agents/seo_auditor.py`) ✅

- [x] `run(page_inspector_report)` → takes PAGE_INSPECTOR_REPORT as input

**E-E-A-T scoring (0–10 each):**
- [x] Experience: word count, dates, FAQ, H2 depth, author presence
- [x] Expertise: author info, content depth, schema types, external citations
- [x] Authoritativeness: HTTPS, external links, Organization schema, OG tags, social links
- [x] Trustworthiness: HTTPS, contact, privacy, phone/email visibility, SSL days

**Core Web Vitals:**
- [x] Flags each metric as Good / Needs Improvement / Poor
- [x] Generates plain-English recommendation for any failing metric
- [x] Returns "Unknown" gracefully when PageSpeed data is not yet wired up

**Local SEO checks:**
- [x] NAP present (phone visible on page)
- [x] LocalBusiness schema with geo coordinates
- [x] Any geographic location signal (zip code, City/ST pattern, "serving", "near me")
- [x] Reviews indicator (schema or social proof copy)
- **Important:** These checks run for every site but are only shown to the user
  for `LocalServices` businesses (filtered in synthesizer). No city is hardcoded.

**Technical SEO checklist:**
- [x] Critical: title, meta desc, H1 (exactly one), HTTPS, canonical, sitemap
- [x] Important: schema, Open Graph, mobile viewport, title/desc optimal length
- [x] Nice-to-have: FAQ, author, Twitter card, dates

**Keyword strategy:**
- [x] Primary keyword inferred from H1 (falls back to title)
- [x] Secondary keywords from H2 cluster (top 5)

**Content Quality Score (0–100):**
- [x] Structure quality: /20
- [x] E-E-A-T signals: /25
- [x] Keyword optimization: /20
- [x] Schema completeness: /15 (awards points for Product/SoftwareApplication schema too, not just LocalBusiness)
- [x] Technical health: /20

### 1g. Agent 3 — Business Decoder (`scripts/agents/business_decoder.py`) ✅

- [x] `run(page_inspector_report)` → takes PAGE_INSPECTOR_REPORT as input
- [x] Classifies business model: SaaS / Ecommerce / LocalServices / Agency / Media / LeadGen / Unknown
  - Uses keyword scoring, schema types, CMS hints, AND robots.txt path fingerprints
  - WooCommerce/add-to-cart paths in robots.txt = strong Ecommerce signal (3 pts each)
  - Returns confidence: high / medium / low based on score margin
- [x] Audience signals: language complexity, price sensitivity, geographic focus, company size target
- [x] Funnel mapping: awareness / consideration / conversion / retention — strength per stage
- [x] Positioning: primary promise, differentiators, proof elements, brand tone
- [x] Competitive signals: mentioned external domains (noise-filtered), conspicuous content gaps

### 1h. Report Synthesizer (`scripts/agents/synthesizer.py`) ✅

- [x] `run(page_report, seo_report, business_report)` → merges all three
- [x] Site Intelligence Score (0–100):
  - SEO Health: 30 pts
  - Technical Health: 25 pts
  - Business Clarity: 25 pts
  - Trust Signals: 20 pts
- [x] Letter grade: A (90+) / B (80+) / C (70+) / D (60+) / F (<60)
- [x] Filters irrelevant issues by business model:
  - `LocalServices` → all issues shown including Local SEO
  - All other models (Ecommerce, SaaS, Agency, Media, Unknown) → Local SEO issues suppressed
- [x] Issues re-scored by business impact (not just technical severity)
  - Security issues boosted +3, Local SEO boosted +2, Performance boosted +1
- [x] Quick Wins (top 3): low effort, high impact — backfills from medium-effort if needed
- [x] Strategic Recommendations (top 3): high effort, high impact
- [x] Schema fix text is business-aware (suggests Product schema for ecommerce, generic for others)

### 1i. CLI Entry Point (`scripts/analyze.py`) ✅

- [x] `python scripts/analyze.py <url> --depth [surface|deep]`
- [x] `surface` → homepage + robots.txt only (fast, ~15 seconds)
- [x] `deep` → full sequence including sitemap + subpages (thorough, ~60 seconds)
- [x] Prints clean readable summary to terminal with score, grade, quick wins
- [x] Saves full `FINAL_REPORT` as JSON to `data/reports/<domain>_<timestamp>.json`
- [x] Graceful error handling: KeyboardInterrupt exits cleanly, exceptions print traceback

- [ ] ✅ **Milestone:** Test on 5+ real URLs across different business types — scores feel accurate
  - Test a local services site (plumber, dentist, restaurant)
  - Test an ecommerce site — confirm no Local SEO issues appear
  - Test a SaaS site — confirm no Local SEO issues appear
  - Confirm business model classification is correct for each

---

## Phase 2 — Data Layer

### 2a. SQLite Setup (`data/db.py`)

- [ ] `init_db()` → create tables if they don't exist
- [ ] `analyses` table:
  ```
  id, url, domain, analysis_date, business_model,
  site_intelligence_score, seo_score, technical_score,
  business_score, trust_score, full_report_json
  ```
- [ ] `sites` table:
  ```
  domain, first_seen, category, location, is_seed (0 or 1)
  ```
- [ ] `save_analysis(final_report)` → insert/update both tables
- [ ] `get_analysis(url)` → return most recent analysis for a URL
- [ ] `get_all_analyses()` → return summary rows for the history sidebar

### 2b. ChromaDB Setup (`data/vector_store.py`)

- [ ] `init_chroma()` → initialize Chroma client with persistence at `data/chroma/`
- [ ] Create three collections:
  - `pages` — full page embeddings (one per analyzed URL)
  - `sections` — H2-level section embeddings (multiple per URL)
  - `issues` — individual recommendation embeddings
- [ ] `embed(text)` → call OpenAI `text-embedding-3-small`, return vector
- [ ] `store_page(final_report)` → embed title + meta + H1 + first 2000 chars of content
  - Metadata stored with vector: url, domain, score, business_model, category, location, is_seed
- [ ] `store_sections(final_report)` → embed each H2 heading + its paragraph text separately
- [ ] `store_issues(final_report)` → embed each recommendation text

### 2c. Hidden Connections Queries

- [ ] `find_similar_sites(url, n=5)` → query `pages` collection for top N nearest neighbors
  - Return: url, domain, score, business_model, category, score delta vs. current site
- [ ] `find_content_gaps(url)` → find H2 topic clusters in similar high-scoring sites absent here
  - Return: list of topic strings the user's page is missing
- [ ] `find_solved_problems(issue_text)` → sites with the same issue that now score higher
  - Return: list of `{ site, old_issue, what_they_changed }` dicts
- [ ] ✅ **Milestone:** Run all three queries on 3 test URLs — results are relevant and useful

---

## Phase 3 — Pre-seed Corpus

> The seed corpus is Fort Lauderdale local businesses — this is the reference dataset
> for the Hidden Connections feature. It has no effect on how any URL is analyzed.

### 3a. Build the Fort Lauderdale URL List

- [ ] Create `corpus/fort_lauderdale_urls.txt` — one URL per line with category comments
- [ ] Research and add ~8–10 URLs per category (target ~70 total):
  - [ ] **Marine / boating** (marinas, yacht brokers, boat repair, charter services)
  - [ ] **Restaurants / dining** (mix of cuisines, fast-casual to fine dining)
  - [ ] **Real estate** (agents, brokerages, property management)
  - [ ] **Healthcare / dental** (dentists, urgent care, specialists)
  - [ ] **Home services** (HVAC, roofing, plumbing, landscaping, pest control)
  - [ ] **Hotels / hospitality** (boutique hotels, vacation rentals, resorts)
  - [ ] **Law firms** (personal injury, real estate law, family law)
  - [ ] **Beauty / wellness** (salons, spas, med spas, fitness studios)
- [ ] For each category: aim for ~5 well-optimized sites (score likely 70+) and ~5 average (40–60)
  - Well-optimized = good reviews, ranked on first page of Google, clear schema
  - Average = still in business but thin content, no schema, weak CTAs

### 3b. Batch Analysis Script (`scripts/seed.py`)

- [ ] Read all URLs from `corpus/fort_lauderdale_urls.txt`
- [ ] Parse category from comment on each line
- [ ] For each URL:
  - [ ] Run full deep analysis via `analyze.py`
  - [ ] Tag as `is_seed = True` in SQLite
  - [ ] Store with correct category and location = "Fort Lauderdale FL"
  - [ ] 2-second pause between requests (be a good internet citizen)
  - [ ] Skip and log any URL that fails — don't crash the whole run
- [ ] Show progress bar with `tqdm`
- [ ] Print final summary: `X succeeded, Y failed, Z skipped`

### 3c. Verify the Corpus

- [ ] All 8 categories represented in ChromaDB — query to confirm
- [ ] Run `find_similar_sites()` on 3 URLs — do the returned sites make sense?
- [ ] Run `find_content_gaps()` on a low-scoring restaurant — are the gaps real?
- [ ] Spot-check 5 analyses manually for accuracy
- [ ] ✅ **Milestone:** Corpus verified — Hidden Connections returns useful results before building UI

---

## Phase 4 — Streamlit UI (`app.py`)

### 4a. Foundation and Auth

- [ ] Set up password gate using `st.secrets["APP_PASSWORD"]`
- [ ] Create two-column layout: narrow sidebar (history) + wide main panel (report)
- [ ] Add app name and one-line description at top

### 4b. URL Input

- [ ] `st.text_input` for URL
- [ ] Analysis depth radio: `Surface (fast)` / `Deep (thorough)`
- [ ] "Analyze" button
- [ ] Validate URL format before running (show error if invalid)

### 4c. Loading State

- [ ] Show spinner while analysis runs
- [ ] Display live status messages as each step completes:
  - "Fetching page..."
  - "Running SEO audit..."
  - "Decoding business signals..."
  - "Searching for hidden connections..."

### 4d. Report Display

- [ ] **Site Intelligence Score** — large number display, color-coded:
  - 0–40: red, 41–69: amber, 70–100: green
- [ ] Score breakdown: four horizontal bars (SEO, Technical, Business, Trust)
- [ ] **Quick Wins** section — top 3 issues, styled as prominent action cards
- [ ] **Strategic Recommendations** — top 3, less prominent
- [ ] Expandable detail sections (collapsed by default):
  - Page Inspector findings
  - SEO Audit (E-E-A-T scores, Core Web Vitals, technical checklist)
  - Business Decoder (model, audience, funnel, positioning)
- [ ] Technical checklist displayed as ✅ / ❌ / ⚠️ icons

### 4e. Hidden Connections Panel ⭐

- [ ] Section header: *"Hidden Connections — What Similar Sites Are Doing Better"*
- [ ] Show top 3 similar sites:
  - Site name, category, their score, score delta vs. current site
- [ ] Content Gaps: "Topics top-performing competitors cover that you don't"
  - Display as bullet list of missing topic areas
- [ ] Solved Problems: "Sites that fixed your biggest issue and how"
  - 2–3 examples with brief description of what changed
- [ ] If fewer than 10 similar sites in DB: show gentle message instead of empty state

### 4f. Sidebar — History

- [ ] List of previously analyzed URLs with their scores
- [ ] Click any to reload that report without re-running analysis

### 4g. Export

- [ ] "Download JSON" button — full `FINAL_REPORT` as `.json`
- [ ] "Download Summary" button — key findings as `.md` file

---

## Phase 5 — Deploy and Demo Prep

- [ ] Push all code to GitHub repo
- [ ] Create `.streamlit/secrets.toml` with API keys (gitignored — add via Streamlit Cloud UI)
- [ ] Connect repo to Streamlit Community Cloud at share.streamlit.io
- [ ] Deploy — confirm public HTTPS URL works
- [ ] Smoke test: analyze 3 Fort Lauderdale business URLs on the live app
- [ ] Verify Hidden Connections returns results for all 3
- [ ] Verify the password gate works
- [ ] Write a 1-page demo script for the SEO pro team member:
  - Which URL to paste first (use a mid-scoring site from the seed list — more dramatic gap to show)
  - Walk-through order: Score → Quick Wins → Hidden Connections
  - The story to tell: *"Here's what your competitor is doing that you're not, and here's proof"*
- [ ] Share the URL + password with team member
- [ ] ✅ **v1 is live**

---

## Phase 6 — v2 Backlog (post-demo)

Revisit after the first demo session. Priority order based on SEO pro feedback:

- [ ] **Wire up PageSpeed API** — real LCP/CLS/INP data (stubbed in current build, needs `PAGESPEED_API_KEY`)
- [ ] **Wire up security headers + SSL checks** — currently stubbed in `page_inspector.py`
- [ ] **Multi-page sampling** — randomly sample 5–10 pages from sitemap, not just homepage
- [ ] **Industry benchmarks** — show score percentile vs. similar business types
- [ ] **Full WCAG accessibility audit** — alt-text coverage %, form labels, heading order, ARIA
- [ ] **Downloadable `.xlsx` issue tracker** — one row per issue, sortable by severity and effort
- [ ] **Competitor auto-discovery** — surface competitor URLs from external link patterns
- [ ] **Fetch caching** — skip re-fetching URLs analyzed in the last 24 hours
- [ ] **Change tracking** — re-analyze a URL and diff against previous score over time
- [ ] **Expand corpus** — add Miami, Orlando, Tampa local businesses
- [ ] **User accounts** — move off shared password to individual logins
- [ ] **FastAPI + React migration** — when you need custom design and multi-user production SaaS
- [ ] **Backlink data** — integrate Google Search Console API or Moz free tier