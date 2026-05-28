"""
ChromaDB vector store — hidden connections engine.

Collections:
  pages    — one embedding per analyzed URL (title + meta + H1 + body)
  sections — one embedding per H2 heading
  issues   — one embedding per recommendation
"""

import math
import os
from pathlib import Path

CHROMA_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"

_chroma_client = None
_openai_client = None


def _get_chroma():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _chroma_client


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from dotenv import load_dotenv
        from openai import OpenAI
        load_dotenv()
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


def init_chroma() -> None:
    """Ensure the three collections exist."""
    c = _get_chroma()
    c.get_or_create_collection("pages")
    c.get_or_create_collection("sections")
    c.get_or_create_collection("issues")


def embed(text: str) -> list[float]:
    """Return an embedding vector for text using text-embedding-3-small."""
    response = _get_openai().embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000],
    )
    return response.data[0].embedding


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _page_text(final_report: dict) -> str:
    """Build the text blob embedded for a page."""
    page = final_report.get("page_report", {})
    meta = page.get("meta", {})
    content = page.get("content", {})
    title = meta.get("title", {}).get("text") or ""
    description = meta.get("description", {}).get("text") or ""
    h1s = content.get("headings", {}).get("h1", {}).get("texts", [])
    body = content.get("body_snippet") or ""
    return " ".join(filter(None, [title, description] + h1s + [body[:2000]]))


# ──────────────────────────────────────────────────────────────
# STORE FUNCTIONS
# ──────────────────────────────────────────────────────────────

def store_page(
    final_report: dict,
    category: str = None,
    location: str = None,
    is_seed: bool = False,
) -> None:
    """Embed the page summary and upsert into the pages collection."""
    url = final_report.get("url") or ""
    if not url:
        return

    text = _page_text(final_report)
    if not text.strip():
        return

    score = final_report.get("site_intelligence_score", {})
    summary = final_report.get("summary", {})

    collection = _get_chroma().get_or_create_collection("pages")
    collection.upsert(
        ids=[url],
        embeddings=[embed(text)],
        metadatas=[{
            "url": url,
            "domain": final_report.get("domain") or "",
            "score": score.get("total", 0),
            "business_model": summary.get("business_model") or "Unknown",
            "category": category or "",
            "location": location or "",
            "is_seed": 1 if is_seed else 0,
            "primary_promise": summary.get("primary_promise") or "",
        }],
        documents=[text],
    )


def store_sections(final_report: dict) -> None:
    """Embed each H2 heading and upsert into the sections collection."""
    url = final_report.get("url") or ""
    if not url:
        return

    h2s = (
        final_report
        .get("page_report", {})
        .get("content", {})
        .get("headings", {})
        .get("h2", {})
        .get("texts", [])
    )
    if not h2s:
        return

    collection = _get_chroma().get_or_create_collection("sections")
    for i, heading in enumerate(h2s):
        if not heading.strip():
            continue
        collection.upsert(
            ids=[f"{url}#h2-{i}"],
            embeddings=[embed(heading)],
            metadatas=[{"url": url, "heading": heading}],
            documents=[heading],
        )


def store_issues(final_report: dict) -> None:
    """Embed each issue and upsert into the issues collection."""
    url = final_report.get("url") or ""
    if not url:
        return

    issues = final_report.get("all_issues_by_impact", [])
    if not issues:
        return

    site_score = final_report.get("site_intelligence_score", {}).get("total", 0)
    collection = _get_chroma().get_or_create_collection("issues")

    for i, issue in enumerate(issues):
        text = issue.get("issue") or ""
        if not text.strip():
            continue
        collection.upsert(
            ids=[f"{url}#issue-{i}"],
            embeddings=[embed(text)],
            metadatas=[{
                "url": url,
                "issue": text,
                "fix": issue.get("fix") or "",
                "site_score": site_score,
            }],
            documents=[text],
        )


# ──────────────────────────────────────────────────────────────
# HIDDEN CONNECTIONS QUERIES
# ──────────────────────────────────────────────────────────────

def find_similar_sites(url: str, n: int = 5) -> list[dict]:
    """
    Find the N most similar pages in the corpus by embedding distance.
    Returns list of {url, domain, score, business_model, category, score_delta}.
    """
    collection = _get_chroma().get_or_create_collection("pages")
    result = collection.get(ids=[url], include=["embeddings", "metadatas"])
    embeddings = result.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        return []

    my_vector = embeddings[0]
    my_score = ((result.get("metadatas") or [{}])[0] or {}).get("score", 0)

    results = collection.query(
        query_embeddings=[my_vector],
        n_results=min(n + 1, collection.count()),
        include=["metadatas", "distances"],
    )

    output = []
    for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
        if (meta or {}).get("url") == url:
            continue
        output.append({
            "url": meta.get("url"),
            "domain": meta.get("domain"),
            "score": meta.get("score"),
            "business_model": meta.get("business_model"),
            "category": meta.get("category"),
            "score_delta": meta.get("score", 0) - my_score,
            "distance": round(dist, 4),
        })
        if len(output) >= n:
            break

    return output


def find_content_gaps(url: str, n_similar: int = 5) -> list[str]:
    """
    H2 topics present in higher-scoring similar sites but semantically absent here.
    Returns list of heading strings.
    """
    similar = find_similar_sites(url, n=n_similar)
    better_sites = [s for s in similar if s["score_delta"] > 0]
    if not better_sites:
        return []

    sections_col = _get_chroma().get_or_create_collection("sections")

    my_data = sections_col.get(where={"url": url}, include=["embeddings"])
    my_embeddings = my_data.get("embeddings")
    if my_embeddings is None:
        my_embeddings = []

    gaps = []
    for site in better_sites:
        their_data = sections_col.get(
            where={"url": site["url"]},
            include=["embeddings", "documents"],
        )
        their_embeddings = their_data.get("embeddings")
        if their_embeddings is None:
            their_embeddings = []
        their_docs = their_data.get("documents") or []
        for emb, doc in zip(their_embeddings, their_docs):
            if not doc:
                continue
            if len(my_embeddings) > 0:
                max_sim = max(_cosine(emb, mine) for mine in my_embeddings)
                if max_sim > 0.8:
                    continue
            if doc not in gaps:
                gaps.append(doc)

    return gaps[:10]


def find_solved_problems(issue_text: str, min_score: int = 65, n: int = 3) -> list[dict]:
    """
    Sites that had a semantically similar issue and now score >= min_score.
    Returns list of {url, domain, score, issue, fix}.
    """
    issues_col = _get_chroma().get_or_create_collection("issues")
    if issues_col.count() == 0:
        return []

    results = issues_col.query(
        query_embeddings=[embed(issue_text)],
        n_results=min(20, issues_col.count()),
        where={"site_score": {"$gte": min_score}},
        include=["metadatas", "distances"],
    )

    output = []
    seen_domains = set()
    for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
        if dist > 0.5:
            continue
        domain = (meta.get("url") or "").split("/")[2] if meta.get("url") else ""
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        output.append({
            "url": meta.get("url"),
            "domain": domain,
            "score": meta.get("site_score"),
            "issue": meta.get("issue"),
            "fix": meta.get("fix"),
        })
        if len(output) >= n:
            break

    return output
