"""Literature search through an isolated Codex web-search turn."""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from ai_scientist.codex_cli import run_codex


PAPER_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "papers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "authors": {"type": "array", "items": {"type": "string"}},
                    "venue": {"type": "string"},
                    "year": {"type": "integer"},
                    "abstract": {"type": "string"},
                    "url": {"type": "string"},
                    "citationCount": {"type": "integer"},
                    "bibtex": {"type": "string"},
                },
                "required": [
                    "title",
                    "authors",
                    "venue",
                    "year",
                    "abstract",
                    "url",
                    "citationCount",
                    "bibtex",
                ],
                "additionalProperties": False,
            },
        },
        "search_note": {"type": "string"},
    },
    "required": ["papers", "search_note"],
    "additionalProperties": False,
}


def _normalize_paper(paper: Dict) -> Dict:
    authors = paper.get("authors", [])
    return {
        "title": paper.get("title", "Unknown Title"),
        "authors": [
            {"name": author if isinstance(author, str) else author.get("name", "Unknown")}
            for author in authors
        ],
        "venue": paper.get("venue", ""),
        "year": paper.get("year", 0),
        "abstract": paper.get("abstract", ""),
        "url": paper.get("url", ""),
        "citationCount": paper.get("citationCount", -1),
        "citationStyles": {"bibtex": paper.get("bibtex", "")},
    }


def search_with_codex(
    query: str,
    result_limit: int = 10,
    *,
    focus: str = "primary",
    timeout_seconds: int | None = None,
) -> Optional[List[Dict]]:
    """Use Codex skills and web search, returning S2-compatible paper dictionaries."""
    if not query:
        return None

    print(f"[Literature Search] Starting isolated Codex {focus} scout.")
    focus_instructions = {
        "primary": (
            "Prioritize the closest primary papers and the simplest relevant baselines."
        ),
        "adversarial": (
            "Act as an adversarial prior-art scout. Prioritize negative results, failed "
            "replications, boundary conditions, and papers that could invalidate or reduce "
            "the novelty of the proposed direction."
        ),
    }
    if focus not in focus_instructions:
        raise ValueError(f"Unknown literature search focus: {focus}")

    prompt = f"""Use the `academic-research-suite` skill and internet web search to find up to
{result_limit} academic papers relevant to this query:

{query}

{focus_instructions[focus]}

Search primary academic sources such as arXiv, official proceedings, journal pages, or DOI
landing pages. Open and verify every returned link. If a primary-source page is blocked,
returns 402/403, or presents a WAF challenge, use the `insane-search` skill as a targeted
access fallback; do not use it for ordinary search. Never invent a paper, metadata, URL,
abstract, citation count, or BibTeX entry. If a citation count cannot be verified, use -1.
If an abstract is unavailable, use an empty string. Prefer direct paper URLs over search-result
pages. Return only verified papers. The `search_note` must briefly state which sources were
searched and any verification limits."""

    raw = run_codex(
        user_message=prompt,
        output_schema=PAPER_SEARCH_SCHEMA,
        timeout_seconds=timeout_seconds,
    )
    payload = json.loads(raw)
    papers = [_normalize_paper(paper) for paper in payload.get("papers", [])]
    note = payload.get("search_note", "")
    print(f"[Literature Search] Codex web search returned {len(papers)} paper(s). {note}")
    return papers or None
