"""Concurrent, failure-isolated literature discovery for ideation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import os
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

from ai_scientist.tools.codex_literature import search_with_codex
from ai_scientist.tools.kurate import KurateSearchTool
from ai_scientist.tools.semantic_scholar import SemanticScholarSearchTool


ARXIV_API_URL = os.getenv("ARXIV_API_URL", "https://export.arxiv.org/api/query")
ARXIV_REQUEST_TIMEOUT = float(os.getenv("ARXIV_REQUEST_TIMEOUT", "20"))
LITERATURE_CODEX_TIMEOUT = int(os.getenv("LITERATURE_CODEX_TIMEOUT", "300"))
LITERATURE_CODEX_RESULT_LIMIT = int(os.getenv("LITERATURE_CODEX_RESULT_LIMIT", "2"))
SOURCE_ORDER = (
    "semantic_scholar",
    "arxiv",
    "kurate",
    "codex_primary",
    "codex_adversarial",
)


@dataclass
class SourceOutcome:
    source: str
    status: str
    papers: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    latency_ms: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "hits": len(self.papers),
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


def build_literature_query(workshop_description: str) -> str:
    """Build a bounded query from the structured Title and Keywords sections."""

    def section(name: str) -> str:
        match = re.search(
            rf"^#\s*{re.escape(name)}\s*$\n(.+?)(?=\n#\s|\Z)",
            workshop_description,
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
        return " ".join(match.group(1).split()) if match else ""

    title = section("Title")
    keywords = section("Keywords")
    if keywords and keywords.casefold() != "machine learning, automated science":
        # Bibliographic APIs are much more reliable with focused keyword queries than
        # with the often long, natural-language research question used as a title.
        cleaned_keywords = re.sub(r"[·,;|]+", " ", keywords)
        return " ".join(cleaned_keywords.split())[:240]
    if title:
        return title[:240]
    return " ".join(workshop_description.split())[:240]


def search_arxiv(query: str, result_limit: int = 5) -> List[Dict[str, Any]]:
    response = requests.get(
        ARXIV_API_URL,
        params={
            "search_query": f'all:"{query[:180]}"',
            "start": 0,
            "max_results": result_limit,
            "sortBy": "relevance",
        },
        timeout=ARXIV_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    atom = "{http://www.w3.org/2005/Atom}"
    arxiv = "{http://arxiv.org/schemas/atom}"
    papers: List[Dict[str, Any]] = []
    for entry in root.findall(f"{atom}entry"):
        entry_url = _element_text(entry.find(f"{atom}id"))
        arxiv_id = entry_url.rstrip("/").split("/")[-1]
        doi = _element_text(entry.find(f"{arxiv}doi"))
        published = _element_text(entry.find(f"{atom}published"))
        papers.append(
            {
                "title": _element_text(entry.find(f"{atom}title")),
                "authors": [
                    {"name": _element_text(author.find(f"{atom}name"))}
                    for author in entry.findall(f"{atom}author")
                ],
                "venue": "arXiv",
                "year": published[:4],
                "abstract": _element_text(entry.find(f"{atom}summary")),
                "url": entry_url,
                "citationCount": -1,
                "externalIds": {
                    key: value
                    for key, value in (("ArXiv", arxiv_id), ("DOI", doi))
                    if value
                },
            }
        )
    return papers


def _element_text(element: Optional[ET.Element]) -> str:
    if element is None or not element.text:
        return ""
    return " ".join(element.text.split())


class MultiSourceLiteratureSurvey:
    """Fan out independent scouts, then deterministically merge their results."""

    def __init__(
        self,
        *,
        result_limit: int = 5,
        include_adversarial: bool = True,
        runners: Optional[Mapping[str, Callable[[str], Optional[List[Dict[str, Any]]]]]] = None,
    ):
        self.result_limit = result_limit
        self.include_adversarial = include_adversarial
        self._custom_runners = dict(runners) if runners is not None else None

    def run(self, query: str) -> Dict[str, Any]:
        runners, skipped = self._build_runners()
        outcomes: Dict[str, SourceOutcome] = dict(skipped)
        print(
            "[Literature Survey] start "
            f"query={query!r} lanes={','.join(runners)}"
        )

        with ThreadPoolExecutor(max_workers=max(1, len(runners))) as executor:
            futures = {
                executor.submit(self._run_source, source, runner, query): source
                for source, runner in runners.items()
            }
            for future in as_completed(futures):
                outcome = future.result()
                outcomes[outcome.source] = outcome
                print(
                    "[Literature Survey] lane "
                    f"source={outcome.source} status={outcome.status} "
                    f"hits={len(outcome.papers)} latency_ms={outcome.latency_ms}"
                )

        ordered_outcomes = [
            outcomes[source] for source in SOURCE_ORDER if source in outcomes
        ]
        ordered_outcomes.extend(
            outcomes[source]
            for source in sorted(outcomes)
            if source not in SOURCE_ORDER
        )
        merged = merge_papers(ordered_outcomes)
        attempted = [item for item in ordered_outcomes if item.status != "skipped"]
        successful = [item for item in attempted if item.status == "ok"]
        if not merged:
            status = "unverified"
        elif len(successful) < 2 or any(item.status == "error" for item in attempted):
            status = "partial"
        else:
            status = "complete"
        print(
            "[Literature Survey] complete "
            f"status={status} sources_ok={len(successful)}/{len(attempted)} "
            f"unique_papers={len(merged)}"
        )
        return {
            "query": query,
            "status": status,
            "sources": [outcome.as_dict() for outcome in ordered_outcomes],
            "papers": merged[: self.result_limit * 3],
        }

    def _build_runners(
        self,
    ) -> tuple[
        Dict[str, Callable[[str], Optional[List[Dict[str, Any]]]]],
        Dict[str, SourceOutcome],
    ]:
        if self._custom_runners is not None:
            return dict(self._custom_runners), {}

        limit = self.result_limit
        codex_limit = min(limit, max(1, LITERATURE_CODEX_RESULT_LIMIT))
        s2 = SemanticScholarSearchTool(max_results=limit)
        runners: Dict[str, Callable[[str], Optional[List[Dict[str, Any]]]]] = {
            "arxiv": lambda query: search_arxiv(query, limit),
            "kurate": KurateSearchTool(max_results=limit).search_for_papers,
            "codex_primary": lambda query: search_with_codex(
                query,
                result_limit=codex_limit,
                focus="primary",
                timeout_seconds=LITERATURE_CODEX_TIMEOUT,
            ),
        }
        skipped: Dict[str, SourceOutcome] = {}
        if s2.S2_API_KEY:
            runners["semantic_scholar"] = s2.search_for_papers
        else:
            skipped["semantic_scholar"] = SourceOutcome(
                source="semantic_scholar",
                status="skipped",
                error="S2_API_KEY not configured",
            )
        if self.include_adversarial:
            runners["codex_adversarial"] = lambda query: search_with_codex(
                query,
                result_limit=codex_limit,
                focus="adversarial",
                timeout_seconds=LITERATURE_CODEX_TIMEOUT,
            )
        return runners, skipped

    @staticmethod
    def _run_source(
        source: str,
        runner: Callable[[str], Optional[List[Dict[str, Any]]]],
        query: str,
    ) -> SourceOutcome:
        started = time.monotonic()
        try:
            papers = runner(query) or []
            if not isinstance(papers, list):
                raise TypeError("source returned a non-list result")
            return SourceOutcome(
                source=source,
                status="ok",
                papers=[paper for paper in papers if isinstance(paper, dict)],
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as error:
            return SourceOutcome(
                source=source,
                status="error",
                error=f"{type(error).__name__}: {error}"[:240],
                latency_ms=int((time.monotonic() - started) * 1000),
            )


def merge_papers(outcomes: Iterable[SourceOutcome]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    aliases: Dict[str, str] = {}
    for outcome in outcomes:
        if outcome.status != "ok":
            continue
        for rank, raw in enumerate(outcome.papers, 1):
            paper = _normalize_paper(raw)
            paper_aliases = _paper_aliases(paper)
            if not paper_aliases:
                continue
            key = next(
                (aliases[alias] for alias in paper_aliases if alias in aliases),
                paper_aliases[0],
            )
            if key not in merged:
                merged[key] = paper
                merged[key]["sources"] = []
                merged[key]["rank_score"] = 0.0
            for alias in paper_aliases:
                aliases[alias] = key
            target = merged[key]
            if outcome.source not in target["sources"]:
                target["sources"].append(outcome.source)
                target["rank_score"] += 1.0 / (60 + rank)
            _fill_missing(target, paper)
            if paper.get("discoverySignals") and not target.get("discoverySignals"):
                target["discoverySignals"] = paper["discoverySignals"]

    for paper in merged.values():
        paper["sources"] = sorted(
            paper["sources"],
            key=lambda source: (
                SOURCE_ORDER.index(source) if source in SOURCE_ORDER else 999,
                source,
            ),
        )
        paper["rank_score"] = round(paper["rank_score"], 6)
    return sorted(
        merged.values(),
        key=lambda paper: (
            -len(paper["sources"]),
            -paper["rank_score"],
            paper.get("title", "").casefold(),
        ),
    )


def _normalize_paper(raw: Dict[str, Any]) -> Dict[str, Any]:
    external_ids = raw.get("externalIds")
    if not isinstance(external_ids, dict):
        external_ids = {}
    url = str(raw.get("url") or raw.get("link") or "")
    arxiv_id = str(external_ids.get("ArXiv") or external_ids.get("arXiv") or "")
    if not arxiv_id:
        match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", url, re.IGNORECASE)
        arxiv_id = match.group(1) if match else ""
    doi = str(external_ids.get("DOI") or "")
    if not doi and url:
        parsed = urlparse(url)
        if parsed.netloc.casefold() in {"doi.org", "dx.doi.org"}:
            doi = parsed.path.lstrip("/")
    authors = raw.get("authors") if isinstance(raw.get("authors"), list) else []
    return {
        "title": " ".join(str(raw.get("title") or "").split()),
        "authors": [
            {"name": str(author.get("name") or "")}
            if isinstance(author, dict)
            else {"name": str(author)}
            for author in authors
        ],
        "venue": str(raw.get("venue") or ""),
        "year": raw.get("year") or "",
        "abstract": " ".join(str(raw.get("abstract") or "").split())[:1800],
        "url": url,
        "citationCount": raw.get("citationCount", -1),
        "externalIds": {
            key: value for key, value in (("DOI", doi), ("ArXiv", arxiv_id)) if value
        },
        "discoverySignals": raw.get("discoverySignals") or {},
    }


def _paper_aliases(paper: Dict[str, Any]) -> List[str]:
    aliases: List[str] = []
    external_ids = paper.get("externalIds", {})
    doi = str(external_ids.get("DOI") or "").casefold().strip()
    if doi:
        aliases.append(f"doi:{doi}")
    arxiv_id = re.sub(r"v\d+$", "", str(external_ids.get("ArXiv") or "").casefold())
    if arxiv_id:
        aliases.append(f"arxiv:{arxiv_id}")
    title = re.sub(r"[^a-z0-9]+", "", str(paper.get("title") or "").casefold())
    if title:
        aliases.append(f"title:{title}")
    return aliases


def _fill_missing(target: Dict[str, Any], candidate: Dict[str, Any]) -> None:
    for key in ("authors", "venue", "year", "abstract", "url", "citationCount"):
        if target.get(key) in (None, "", [], -1) and candidate.get(key) not in (
            None,
            "",
            [],
            -1,
        ):
            target[key] = candidate[key]
    target_ids = target.setdefault("externalIds", {})
    for key, value in candidate.get("externalIds", {}).items():
        target_ids.setdefault(key, value)


def format_survey_for_prompt(survey: Dict[str, Any]) -> str:
    lines = [
        f"Survey status: {survey.get('status', 'unverified')}",
        "Source outcomes:",
    ]
    for source in survey.get("sources", []):
        suffix = f"; error={source['error']}" if source.get("error") else ""
        lines.append(
            f"- {source.get('source')}: {source.get('status')} "
            f"({source.get('hits', 0)} hits){suffix}"
        )
    lines.append("Verified/discovered papers:")
    for index, paper in enumerate(survey.get("papers", []), 1):
        authors = ", ".join(
            author.get("name", "") for author in paper.get("authors", [])[:4]
        )
        abstract = str(paper.get("abstract") or "")[:700]
        signal_note = (
            f" Kurate discovery signals={paper['discoverySignals']}; not peer review."
            if paper.get("discoverySignals")
            else ""
        )
        lines.append(
            f"{index}. {paper.get('title')} ({paper.get('year') or 'year unknown'}). "
            f"{authors}. Sources={','.join(paper.get('sources', []))}. "
            f"URL={paper.get('url') or 'unavailable'}. Abstract={abstract}.{signal_note}"
        )
    if survey.get("status") != "complete":
        lines.append(
            "Novelty verification is incomplete. State this limitation and avoid claiming "
            "that missing search results prove novelty."
        )
    return "\n".join(lines)
