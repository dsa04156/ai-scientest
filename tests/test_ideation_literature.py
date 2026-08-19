import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ai_scientist.perform_ideation_temp_free import generate_temp_free_idea


class IdeationLiteratureTests(unittest.TestCase):
    @patch("ai_scientist.perform_ideation_temp_free.get_response_from_llm")
    @patch("ai_scientist.perform_ideation_temp_free.MultiSourceLiteratureSurvey")
    def test_survey_runs_once_and_is_saved_beside_ideas(self, survey_type, respond):
        survey = {
            "query": "Harness — agents",
            "status": "complete",
            "sources": [
                {"source": "arxiv", "status": "ok", "hits": 1, "error": ""},
                {
                    "source": "codex_adversarial",
                    "status": "ok",
                    "hits": 1,
                    "error": "",
                },
            ],
            "papers": [],
        }
        survey_type.return_value.run.return_value = survey
        respond.return_value = (
            "ACTION:\nFinalizeIdea\n\nARGUMENTS:\n"
            + json.dumps(
                {
                    "idea": {
                        "Name": "simple_harness_test",
                        "Title": "Simple Harness Test",
                    }
                }
            ),
            [],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            idea_path = Path(temp_dir) / "ideas.json"
            ideas = generate_temp_free_idea(
                str(idea_path),
                client=Mock(),
                model="codex",
                workshop_description="# Title\nHarness\n# Keywords\nagents",
                max_num_generations=3,
                num_reflections=1,
                reload_ideas=False,
            )
            artifact = Path(temp_dir) / "ideas.literature.json"

            self.assertEqual(survey_type.return_value.run.call_count, 1)
            self.assertEqual(json.loads(artifact.read_text())["status"], "complete")
            self.assertEqual(len(ideas), 3)
            for prompt in respond.call_args_list:
                self.assertIn("automatic multi-source literature survey", prompt.kwargs["prompt"])


if __name__ == "__main__":
    unittest.main()
