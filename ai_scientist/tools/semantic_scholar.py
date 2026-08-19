import os
import requests
import time
import warnings
from typing import Dict, List, Optional, Union

import backoff

from ai_scientist.tools.base_tool import BaseTool
from ai_scientist.tools.codex_literature import search_with_codex

S2_MAX_TRIES = int(os.getenv("S2_MAX_TRIES", "3"))
S2_REQUEST_TIMEOUT = float(os.getenv("S2_REQUEST_TIMEOUT", "20"))


def give_up_on_client_error(error: requests.exceptions.RequestException) -> bool:
    """Retry rate limits and server errors, but not other HTTP 4xx responses."""
    response = getattr(error, "response", None)
    return bool(
        response is not None
        and 400 <= response.status_code < 500
        and response.status_code != 429
    )


def on_backoff(details: Dict) -> None:
    print(
        f"Backing off {details['wait']:0.1f} seconds after {details['tries']} tries "
        f"calling function {details['target'].__name__} at {time.strftime('%X')}"
    )


class SemanticScholarSearchTool(BaseTool):
    def __init__(
        self,
        name: str = "SearchSemanticScholar",
        description: str = (
            "Search for relevant literature using Semantic Scholar. "
            "Provide a search query to find relevant papers."
        ),
        max_results: int = 10,
    ):
        parameters = [
            {
                "name": "query",
                "type": "str",
                "description": "The search query to find relevant papers.",
            }
        ]
        super().__init__(name, description, parameters)
        self.max_results = max_results
        self.S2_API_KEY = os.getenv("S2_API_KEY")
        if not self.S2_API_KEY:
            print(
                "[Literature Search] No S2_API_KEY found; Codex academic web search "
                "will be used without calling the rate-limited S2 endpoint."
            )

    def use_tool(self, query: str) -> Optional[str]:
        if not self.S2_API_KEY:
            return self._use_codex_fallback(query)
        try:
            papers = self.search_for_papers(query)
        except requests.exceptions.RequestException as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            reason = "rate limited (HTTP 429)" if status == 429 else str(error)
            print(f"[Semantic Scholar] Search failed because it was {reason}.")
            return self._use_codex_fallback(query)
        if papers:
            return self.format_papers(papers)
        else:
            return "No papers found."

    def _use_codex_fallback(self, query: str) -> str:
        try:
            papers = search_with_codex(query, result_limit=self.max_results)
        except Exception as error:
            message = (
                "Both Semantic Scholar and Codex web literature search are unavailable "
                f"({error}). Continue without literature results and clearly note that "
                "novelty was not verified."
            )
            print(f"[Literature Search] {message}")
            return message
        return self.format_papers(papers) if papers else "No verified papers found."

    @backoff.on_exception(
        backoff.expo,
        (requests.exceptions.HTTPError, requests.exceptions.ConnectionError),
        on_backoff=on_backoff,
        giveup=give_up_on_client_error,
        max_tries=S2_MAX_TRIES,
        max_value=8,
    )
    def search_for_papers(self, query: str) -> Optional[List[Dict]]:
        if not query:
            return None

        headers = {}
        if self.S2_API_KEY:
            headers["X-API-KEY"] = self.S2_API_KEY

        rsp = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            headers=headers,
            params={
                "query": query,
                "limit": self.max_results,
                "fields": (
                    "paperId,externalIds,url,title,authors,venue,year,abstract,"
                    "citationCount"
                ),
            },
            timeout=S2_REQUEST_TIMEOUT,
        )
        print(f"Response Status Code: {rsp.status_code}")
        print(f"Response Content: {rsp.text[:500]}")
        rsp.raise_for_status()
        results = rsp.json()
        total = results.get("total", 0)
        if total == 0:
            return None

        papers = results.get("data", [])
        # Sort papers by citationCount in descending order
        papers.sort(key=lambda x: x.get("citationCount", 0), reverse=True)
        return papers

    def format_papers(self, papers: List[Dict]) -> str:
        paper_strings = []
        for i, paper in enumerate(papers):
            authors = ", ".join(
                [author.get("name", "Unknown") for author in paper.get("authors", [])]
            )
            paper_strings.append(
                f"""{i + 1}: {paper.get("title", "Unknown Title")}. {authors}. {paper.get("venue", "Unknown Venue")}, {paper.get("year", "Unknown Year")}.
Number of citations: {paper.get("citationCount", "N/A")}
URL: {paper.get("url", "No URL available.")}
Abstract: {paper.get("abstract", "No abstract available.")}"""
            )
        return "\n\n".join(paper_strings)


@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.HTTPError, requests.exceptions.ConnectionError),
    on_backoff=on_backoff,
    giveup=give_up_on_client_error,
    max_tries=S2_MAX_TRIES,
    max_value=8,
)
def _search_for_papers(query, result_limit=10) -> Union[None, List[Dict]]:
    S2_API_KEY = os.getenv("S2_API_KEY")
    headers = {}
    if not S2_API_KEY:
        warnings.warn(
            "No Semantic Scholar API key found. Requests will be subject to stricter rate limits."
        )
    else:
        headers["X-API-KEY"] = S2_API_KEY

    if not query:
        return None

    rsp = requests.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        headers=headers,
        params={
            "query": query,
            "limit": result_limit,
            "fields": (
                "paperId,externalIds,url,title,authors,venue,year,abstract,"
                "citationStyles,citationCount"
            ),
        },
        timeout=S2_REQUEST_TIMEOUT,
    )
    print(f"Response Status Code: {rsp.status_code}")
    print(
        f"Response Content: {rsp.text[:500]}"
    )  # Print the first 500 characters of the response content
    rsp.raise_for_status()
    results = rsp.json()
    total = results["total"]
    time.sleep(1.0)
    if not total:
        return None

    papers = results["data"]
    return papers


def search_for_papers(query, result_limit=10) -> Union[None, List[Dict]]:
    """Search for citations via keyed S2, falling back to Codex web search."""
    if not os.getenv("S2_API_KEY"):
        try:
            return search_with_codex(query, result_limit=result_limit)
        except Exception as error:
            print(f"[Literature Search] Codex web search failed: {error}")
            return None
    try:
        return _search_for_papers(query, result_limit=result_limit)
    except requests.exceptions.RequestException as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        reason = "HTTP 429 rate limit" if status == 429 else str(error)
        print(
            f"[Semantic Scholar] Search failed after {S2_MAX_TRIES} attempts: {reason}"
        )
        try:
            return search_with_codex(query, result_limit=result_limit)
        except Exception as fallback_error:
            print(f"[Literature Search] Codex web search failed: {fallback_error}")
            return None
