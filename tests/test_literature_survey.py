import threading
import unittest
from unittest.mock import Mock, patch

from ai_scientist.tools.literature_survey import (
    MultiSourceLiteratureSurvey,
    SourceOutcome,
    build_literature_query,
    merge_papers,
    search_arxiv,
)


def paper(title, *, arxiv="", doi="", url=""):
    return {
        "title": title,
        "authors": [{"name": "A. Author"}],
        "year": 2026,
        "abstract": "Abstract",
        "url": url,
        "externalIds": {
            key: value for key, value in (("ArXiv", arxiv), ("DOI", doi)) if value
        },
    }


class LiteratureSurveyTests(unittest.TestCase):
    def test_custom_lanes_really_run_concurrently(self):
        barrier = threading.Barrier(2, timeout=2)

        def runner(query):
            barrier.wait()
            return [paper(f"{query} result")]

        survey = MultiSourceLiteratureSurvey(
            runners={"lane_a": runner, "lane_b": runner}
        ).run("harness")

        self.assertEqual(survey["status"], "complete")
        self.assertEqual({item["status"] for item in survey["sources"]}, {"ok"})

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_s2_key_skips_only_s2(self):
        survey = MultiSourceLiteratureSurvey(include_adversarial=False)

        runners, skipped = survey._build_runners()

        self.assertEqual(skipped["semantic_scholar"].status, "skipped")
        self.assertEqual(set(runners), {"arxiv", "kurate", "codex_primary"})

    @patch("ai_scientist.tools.literature_survey.search_with_codex", return_value=[])
    def test_codex_scouts_use_bounded_deep_verification_limit(self, search):
        runners, _ = MultiSourceLiteratureSurvey(result_limit=5)._build_runners()

        runners["codex_primary"]("harness")
        runners["codex_adversarial"]("harness")

        self.assertEqual(search.call_args_list[0].kwargs["result_limit"], 2)
        self.assertEqual(search.call_args_list[1].kwargs["result_limit"], 2)

    def test_one_lane_failure_keeps_results_and_marks_partial(self):
        def fail(_query):
            raise RuntimeError("blocked")

        result = MultiSourceLiteratureSurvey(
            runners={
                "good": lambda _query: [paper("Useful paper")],
                "bad": fail,
            }
        ).run("harness")

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["papers"][0]["title"], "Useful paper")
        self.assertEqual(
            next(item for item in result["sources"] if item["source"] == "bad")[
                "status"
            ],
            "error",
        )

    def test_all_lane_failures_are_explicitly_unverified(self):
        def fail(_query):
            raise RuntimeError("offline")

        result = MultiSourceLiteratureSurvey(
            runners={"a": fail, "b": fail}
        ).run("harness")

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["papers"], [])

    def test_dedup_merges_identifiers_and_provenance(self):
        outcomes = [
            SourceOutcome(
                "semantic_scholar",
                "ok",
                [
                    paper(
                        "Same Paper",
                        arxiv="2601.00001",
                        doi="10.1000/example",
                    )
                ],
            ),
            SourceOutcome(
                "arxiv",
                "ok",
                [paper("Same Paper", arxiv="2601.00001v2")],
            ),
            SourceOutcome(
                "codex_primary",
                "ok",
                [paper("Same Paper", url="https://doi.org/10.1000/example")],
            ),
        ]

        merged = merge_papers(outcomes)

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["sources"],
            ["semantic_scholar", "arxiv", "codex_primary"],
        )

    def test_order_is_independent_of_completion_order(self):
        first = SourceOutcome("arxiv", "ok", [paper("Alpha"), paper("Beta")])
        second = SourceOutcome("codex_primary", "ok", [paper("Beta"), paper("Alpha")])

        forward = [item["title"] for item in merge_papers([first, second])]
        reverse = [item["title"] for item in merge_papers([second, first])]

        self.assertEqual(forward, reverse)

    @patch("ai_scientist.tools.literature_survey.requests.get")
    def test_arxiv_parser_tolerates_missing_optional_metadata(self, request_get):
        response = Mock()
        response.text = """<?xml version='1.0' encoding='UTF-8'?>
        <feed xmlns='http://www.w3.org/2005/Atom'>
          <entry>
            <id>https://arxiv.org/abs/2601.00001v1</id>
            <title> Test Paper </title>
            <summary> Summary text. </summary>
            <author><name>A. Author</name></author>
          </entry>
        </feed>"""
        response.raise_for_status.return_value = None
        request_get.return_value = response

        papers = search_arxiv("test", 3)

        self.assertEqual(papers[0]["title"], "Test Paper")
        self.assertEqual(papers[0]["year"], "")
        self.assertEqual(papers[0]["externalIds"]["ArXiv"], "2601.00001v1")

    def test_query_uses_title_and_keywords_not_full_abstract(self):
        query = build_literature_query(
            "# Title\nSelf-Evolving Harness\n# Keywords\nagents, evaluation\n"
            "# Abstract\nThis long abstract must not appear in the query."
        )

        self.assertEqual(query, "agents evaluation")
        self.assertNotIn("long abstract", query)


if __name__ == "__main__":
    unittest.main()
