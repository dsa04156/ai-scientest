import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_scientist.idea_recommendation import evaluate_ideas, recommendation_path_for


class IdeaRecommendationTests(unittest.TestCase):
    def test_recommendation_path_is_an_adjacent_sidecar(self):
        self.assertEqual(
            recommendation_path_for("runs/topic.json"),
            Path("runs/topic.recommendations.json"),
        )

    @patch("ai_scientist.idea_recommendation.run_codex")
    def test_evaluate_ideas_validates_and_writes_comparative_scores(self, run_codex):
        payload = {
            "rubric_version": "pre-experiment-v1",
            "basis": "proposal_only",
            "confidence": "low",
            "recommended_index": 1,
            "summary": "두 번째 후보를 먼저 검증합니다.",
            "assessments": [
                {
                    "idea_index": 0,
                    "score": 70,
                    "verdict": "유망",
                    "rationale": "가설은 명확하지만 통제가 부족합니다.",
                    "strength": "명확한 가설",
                    "main_risk": "통제 부족",
                    "scores": {"novelty": 18, "falsifiability": 20, "feasibility": 18, "experimental_rigor": 14},
                },
                {
                    "idea_index": 1,
                    "score": 81,
                    "verdict": "우선 검증",
                    "rationale": "판별력이 높고 실행 범위가 제한적입니다.",
                    "strength": "판별적 실험",
                    "main_risk": "신규성 확인 필요",
                    "scores": {"novelty": 19, "falsifiability": 22, "feasibility": 21, "experimental_rigor": 19},
                },
            ],
        }
        run_codex.return_value = json.dumps(payload, ensure_ascii=False)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ideas.recommendations.json"
            result = evaluate_ideas([{"Title": "A"}, {"Title": "B"}], output)

            self.assertEqual(result["recommended_index"], 1)
            self.assertEqual(json.loads(output.read_text())["assessments"][1]["score"], 81)
            self.assertEqual(run_codex.call_args.kwargs["model"], "codex")
            self.assertIn("output_schema", run_codex.call_args.kwargs)

    @patch("ai_scientist.idea_recommendation.run_codex")
    def test_rejects_a_total_that_does_not_match_components(self, run_codex):
        run_codex.return_value = json.dumps(
            {
                "rubric_version": "pre-experiment-v1",
                "basis": "proposal_only",
                "confidence": "low",
                "recommended_index": 0,
                "summary": "검증 필요",
                "assessments": [
                    {
                        "idea_index": 0,
                        "score": 99,
                        "verdict": "우선 검증",
                        "rationale": "설명",
                        "strength": "강점",
                        "main_risk": "위험",
                        "scores": {"novelty": 10, "falsifiability": 10, "feasibility": 10, "experimental_rigor": 10},
                    }
                ],
            },
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "component sum"):
                evaluate_ideas([{"Title": "A"}], Path(tmp) / "out.json")


if __name__ == "__main__":
    unittest.main()
