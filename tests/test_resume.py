import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_scientist.treesearch.agent_manager import AgentManager
from ai_scientist.treesearch.perform_experiments_bfts_with_agentmanager import (
    _resume_manager,
)


class ExperimentResumeTests(unittest.TestCase):
    def test_completed_checkpoint_advances_to_next_main_stage(self):
        cfg = SimpleNamespace(
            agent=SimpleNamespace(
                steps=5,
                stages=SimpleNamespace(
                    stage1_max_iters=20,
                    stage2_max_iters=12,
                    stage3_max_iters=12,
                    stage4_max_iters=18,
                ),
                search=SimpleNamespace(num_drafts=3),
            )
        )
        task_desc = {
            "Title": "Resume test",
            "Abstract": "Test checkpoint restoration.",
            "Short Hypothesis": "A completed checkpoint can advance safely.",
            "Experiments": ["Run the next stage."],
            "Risk Factors and Limitations": ["Synthetic test only."],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            original = AgentManager(
                task_desc=__import__("json").dumps(task_desc),
                cfg=cfg,
                workspace_dir=workspace,
            )
            checkpoint_path = Path(temp_dir) / "checkpoint.pkl"
            with checkpoint_path.open("wb") as checkpoint_file:
                pickle.dump(
                    {
                        "journals": original.journals,
                        "stage_history": original.stage_history,
                        "task_desc": original.task_desc,
                        "cfg": cfg,
                        "workspace_dir": workspace,
                        "current_stage": original.current_stage,
                    },
                    checkpoint_file,
                )

            restored_cfg, restored = _resume_manager(checkpoint_path)

        self.assertIs(restored_cfg, restored.cfg)
        self.assertEqual(restored.current_stage.name, "2_baseline_tuning_1_first_attempt")
        self.assertIn("1_initial_implementation_1_preliminary", restored.journals)
        self.assertIn("2_baseline_tuning_1_first_attempt", restored.journals)
        self.assertEqual(restored.stage_history[-1].from_stage, "1_initial_implementation_1_preliminary")


if __name__ == "__main__":
    unittest.main()
