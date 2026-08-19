"""Optional Kurate discovery adapter.

Kurate's JSON endpoints are currently public but undocumented and unversioned. This
adapter is deliberately fail-open and treats ratings as discovery signals, not evidence.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import requests

from ai_scientist.tools.base_tool import BaseTool


KURATE_BASE_URL = os.getenv("KURATE_BASE_URL", "https://kurate.org").rstrip("/")
KURATE_REQUEST_TIMEOUT = float(os.getenv("KURATE_REQUEST_TIMEOUT", "12"))


def _search_terms(query: str, limit: int = 3) -> List[str]:
    stopwords = {
        "about",
        "agentic",
        "evaluation",
        "research",
        "study",
        "using",
        "with",
    }
    terms: List[str] = []
    for term in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", query.lower()):
        normalized = term.strip("-")
        if normalized and normalized not in stopwords and normalized not in terms:
            terms.append(normalized)
    return terms[:limit] or [query[:80]]


class KurateSearchTool(BaseTool):
    def __init__(
        self,
        name: str = "SearchKurate",
        description: str = (
            "Search Kurate as an optional recent-paper discovery signal. Returned AI "
            "ratings are not peer review and every claim must be checked at the linked "
            "primary paper."
        ),
        max_results: int = 5,
        session: Any = requests,
    ):
        super().__init__(
            name,
            description,
            [
                {
                    "name": "query",
                    "type": "str",
                    "description": "A short topic or keyword query.",
                }
            ],
        )
        self.max_results = max_results
        self.session = session

    def use_tool(self, query: str) -> str:
        try:
            papers = self.search_for_papers(query)
        except (requests.RequestException, ValueError, TypeError) as error:
            return (
                "Kurate enrichment unavailable. Continue with primary-source searches; "
                f"do not interpret this absence as evidence. ({error})"
            )
        if not papers:
            return (
                "No matching Kurate discovery entries found. This is not negative "
                "evidence; continue with Semantic Scholar, arXiv, and primary sources."
            )
        return self.format_papers(papers)

    def search_for_papers(self, query: str) -> List[Dict[str, Any]]:
        if not query.strip():
            return []

        relevance_terms = _search_terms(query, limit=8)
        rows_by_id: Dict[str, Dict[str, Any]] = {}
        candidate_limit = self.max_results * 3
        for term in relevance_terms[:3]:
            response = self.session.get(
                f"{KURATE_BASE_URL}/api/papers-list",
                params={"search": term, "limit": self.max_results},
                timeout=KURATE_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("rows", []) if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                paper_id = str(row.get("paper_id") or row.get("id") or "")
                if paper_id:
                    rows_by_id.setdefault(paper_id, row)
                if len(rows_by_id) >= candidate_limit:
                    break
            if len(rows_by_id) >= candidate_limit:
                break

        ranked_papers: List[tuple[int, Dict[str, Any]]] = []
        minimum_overlap = 2 if len(relevance_terms) >= 2 else 1
        for paper_id, row in list(rows_by_id.items())[:candidate_limit]:
            paper = self._fetch_detail(paper_id) or row
            normalized = self._normalize(paper, row)
            searchable = (
                f"{normalized.get('title', '')} {normalized.get('abstract', '')}"
            ).casefold()
            overlap = sum(term in searchable for term in relevance_terms)
            if normalized.get("title") and overlap >= minimum_overlap:
                ranked_papers.append((overlap, normalized))
        ranked_papers.sort(
            key=lambda item: (-item[0], item[1].get("title", "").casefold())
        )
        return [paper for _, paper in ranked_papers[: self.max_results]]

    def _fetch_detail(self, paper_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.session.get(
                f"{KURATE_BASE_URL}/api/papers/{paper_id}",
                timeout=KURATE_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        paper = payload.get("paper")
        return paper if isinstance(paper, dict) else None

    @staticmethod
    def _normalize(paper: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
        authors = paper.get("authors") or row.get("authors") or []
        if not isinstance(authors, list):
            authors = []
        arxiv_id = str(paper.get("arxiv_id") or row.get("arxiv_id") or "")
        link = str(paper.get("link") or row.get("link") or "")
        if not link and arxiv_id:
            link = f"https://arxiv.org/abs/{arxiv_id}"
        ratings = row.get("ratings") if isinstance(row.get("ratings"), dict) else {}
        return {
            "title": str(paper.get("title") or row.get("title") or ""),
            "authors": [
                {"name": str(author.get("name", ""))}
                if isinstance(author, dict)
                else {"name": str(author)}
                for author in authors
            ],
            "venue": "Kurate discovery / arXiv",
            "year": str(paper.get("published") or "")[:4],
            "abstract": str(paper.get("abstract") or ""),
            "url": link,
            "citationCount": -1,
            "externalIds": {"ArXiv": arxiv_id} if arxiv_id else {},
            "discoverySignals": {
                key: ratings[key]
                for key in ("score", "novelty", "rigor", "replication_value", "refutation_value")
                if key in ratings
            },
        }

    @staticmethod
    def format_papers(papers: List[Dict[str, Any]]) -> str:
        sections = [
            "Kurate discovery signals (not peer review; verify against primary papers):"
        ]
        for index, paper in enumerate(papers, 1):
            signals = paper.get("discoverySignals") or {}
            signal_text = ", ".join(f"{key}={value}" for key, value in signals.items())
            sections.append(
                f"{index}. {paper.get('title', 'Unknown title')}\n"
                f"Primary URL: {paper.get('url') or 'unavailable'}\n"
                f"Signals: {signal_text or 'unavailable'}\n"
                f"Abstract: {paper.get('abstract') or 'unavailable'}"
            )
        return "\n\n".join(sections)
