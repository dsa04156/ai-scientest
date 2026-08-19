import unittest
from unittest.mock import Mock, patch

import requests

from ai_scientist.tools.semantic_scholar import (
    SemanticScholarSearchTool,
    search_for_papers,
)


def rate_limited_response():
    response = Mock()
    response.status_code = 429
    response.text = '{"message":"Too Many Requests"}'
    error = requests.exceptions.HTTPError(response=response)
    response.raise_for_status.side_effect = error
    return response


class SemanticScholarTests(unittest.TestCase):
    @patch.dict("os.environ", {"S2_API_KEY": "test-key"})
    @patch("ai_scientist.tools.semantic_scholar.search_with_codex")
    @patch("ai_scientist.tools.semantic_scholar.time.sleep", return_value=None)
    @patch("ai_scientist.tools.semantic_scholar.requests.get")
    def test_ideation_search_uses_codex_fallback_after_three_429s(
        self, request_get, _sleep, codex_search
    ):
        request_get.side_effect = [
            rate_limited_response(),
            rate_limited_response(),
            rate_limited_response(),
        ]
        codex_search.return_value = [
            {
                "title": "Harness Evaluation",
                "authors": [{"name": "A. Researcher"}],
                "venue": "arXiv",
                "year": 2026,
                "abstract": "An abstract.",
                "url": "https://arxiv.org/abs/1234.5678",
                "citationCount": -1,
            }
        ]
        tool = SemanticScholarSearchTool()

        result = tool.use_tool("agent harness evaluation")

        self.assertEqual(request_get.call_count, 3)
        codex_search.assert_called_once_with("agent harness evaluation", result_limit=10)
        self.assertIn("Harness Evaluation", result)
        self.assertIn("https://arxiv.org/abs/1234.5678", result)
        self.assertEqual(request_get.call_args.kwargs["timeout"], 20.0)
        fields = request_get.call_args.kwargs["params"]["fields"]
        self.assertIn("paperId", fields)
        self.assertIn("externalIds", fields)
        self.assertIn("url", fields)

    @patch.dict("os.environ", {"S2_API_KEY": "test-key"})
    @patch("ai_scientist.tools.semantic_scholar.search_with_codex")
    @patch("ai_scientist.tools.semantic_scholar.time.sleep", return_value=None)
    @patch("ai_scientist.tools.semantic_scholar.requests.get")
    def test_writeup_search_uses_codex_fallback_after_three_429s(
        self, request_get, _sleep, codex_search
    ):
        request_get.side_effect = [
            rate_limited_response(),
            rate_limited_response(),
            rate_limited_response(),
        ]

        codex_search.return_value = [{"title": "Harness Evaluation"}]
        result = search_for_papers("agent harness evaluation")

        self.assertEqual(result, [{"title": "Harness Evaluation"}])
        self.assertEqual(request_get.call_count, 3)

    @patch.dict("os.environ", {"S2_API_KEY": "test-key"})
    @patch("ai_scientist.tools.semantic_scholar.search_with_codex", return_value=None)
    @patch("ai_scientist.tools.semantic_scholar.requests.get")
    def test_non_rate_limit_client_error_is_not_retried(
        self, request_get, _codex_search
    ):
        response = Mock()
        response.status_code = 400
        response.text = "bad query"
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=response
        )
        request_get.return_value = response

        result = search_for_papers("bad query")

        self.assertIsNone(result)
        self.assertEqual(request_get.call_count, 1)

    @patch.dict("os.environ", {}, clear=True)
    @patch("ai_scientist.tools.semantic_scholar.search_with_codex")
    @patch("ai_scientist.tools.semantic_scholar.requests.get")
    def test_missing_key_skips_s2_and_uses_codex(self, request_get, codex_search):
        codex_search.return_value = [{"title": "Web Result"}]

        result = search_for_papers("agent harness evaluation", result_limit=4)

        self.assertEqual(result, [{"title": "Web Result"}])
        request_get.assert_not_called()
        codex_search.assert_called_once_with(
            "agent harness evaluation", result_limit=4
        )


if __name__ == "__main__":
    unittest.main()
