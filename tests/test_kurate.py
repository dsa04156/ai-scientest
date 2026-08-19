import unittest
from unittest.mock import Mock

import requests

from ai_scientist.tools.kurate import KurateSearchTool


def response(payload, *, status_error=None):
    result = Mock()
    result.json.return_value = payload
    result.raise_for_status.side_effect = status_error
    return result


class KurateSearchTests(unittest.TestCase):
    def test_search_enriches_rows_with_primary_paper_detail(self):
        session = Mock()
        session.get.side_effect = [
            response(
                {
                    "rows": [
                        {
                            "paper_id": "paper-1",
                            "title": "Harness Study",
                            "ratings": {"score": 7.5, "novelty": 6.0},
                        }
                    ]
                }
            ),
            response(
                {
                    "paper": {
                        "id": "paper-1",
                        "title": "Harness Study",
                        "authors": ["A. Author"],
                        "abstract": "A primary abstract.",
                        "published": "2026-01-02T00:00:00Z",
                        "arxiv_id": "2601.00001v1",
                        "link": "https://arxiv.org/abs/2601.00001v1",
                    }
                }
            ),
        ]
        tool = KurateSearchTool(max_results=1, session=session)

        papers = tool.search_for_papers("harness")

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["externalIds"]["ArXiv"], "2601.00001v1")
        self.assertEqual(papers[0]["discoverySignals"]["score"], 7.5)
        self.assertIn("A primary abstract", papers[0]["abstract"])

    def test_schema_drift_is_fail_open(self):
        session = Mock()
        session.get.return_value = response({"unexpected": []})
        tool = KurateSearchTool(session=session)

        self.assertEqual(tool.search_for_papers("agent"), [])

    def test_tool_failure_warns_without_treating_absence_as_evidence(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError("offline")
        tool = KurateSearchTool(session=session)

        result = tool.use_tool("agent")

        self.assertIn("unavailable", result)
        self.assertIn("do not interpret this absence as evidence", result)


if __name__ == "__main__":
    unittest.main()
