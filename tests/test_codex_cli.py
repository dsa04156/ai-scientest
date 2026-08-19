import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_scientist.codex_cli import _strict_output_schema, run_codex
from ai_scientist.treesearch.parallel_agent import _extract_plan_and_code


class CodexCliTests(unittest.TestCase):
    def test_code_only_completion_is_accepted(self):
        parsed = _extract_plan_and_code("```python\nprint('ready')\n```")

        self.assertIsNotNone(parsed)
        plan, code = parsed
        self.assertIn("generated directly", plan)
        self.assertEqual(code.strip(), 'print("ready")')

    def test_output_schema_is_strict_at_every_object_level(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"score": {"type": "number"}},
                    },
                },
            },
        }

        normalized = _strict_output_schema(schema)

        self.assertEqual(normalized["required"], ["name", "items"])
        self.assertFalse(normalized["additionalProperties"])
        nested = normalized["properties"]["items"]["items"]
        self.assertEqual(nested["required"], ["score"])
        self.assertFalse(nested["additionalProperties"])
        self.assertNotIn("additionalProperties", schema)

    @patch("ai_scientist.codex_cli.shutil.which", return_value="/usr/bin/codex")
    @patch("ai_scientist.codex_cli.subprocess.run")
    def test_research_reasoning_defaults_to_xhigh(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 0, "OK", "")

        with patch.dict("os.environ", {}, clear=True):
            result = run_codex(user_message="test")

        self.assertEqual(result, "OK")
        command = run.call_args.args[0]
        config_index = command.index("-c")
        self.assertEqual(command[config_index + 1], 'model_reasoning_effort="xhigh"')

    @patch("ai_scientist.codex_cli.shutil.which", return_value="/usr/bin/codex")
    @patch("ai_scientist.codex_cli.subprocess.run")
    def test_explicit_timeout_is_passed_to_subprocess(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 0, "OK", "")

        run_codex(user_message="test", timeout_seconds=45)

        self.assertEqual(run.call_args.kwargs["timeout"], 45)

    @patch("ai_scientist.codex_cli.shutil.which", return_value="/usr/bin/codex")
    @patch("ai_scientist.codex_cli.subprocess.run")
    def test_each_call_gets_an_isolated_codex_home_with_auth(self, run, _which):
        def inspect_call(*_args, **kwargs):
            isolated_home = Path(kwargs["env"]["CODEX_HOME"])
            self.assertTrue((isolated_home / "auth.json").is_file())
            self.assertNotEqual(isolated_home, source_home)
            return subprocess.CompletedProcess([], 0, "OK", "")

        run.side_effect = inspect_call
        with tempfile.TemporaryDirectory() as temp_dir:
            source_home = Path(temp_dir)
            (source_home / "auth.json").write_text('{"token":"redacted-test"}')
            with patch.dict("os.environ", {"CODEX_HOME": str(source_home)}, clear=True):
                self.assertEqual(run_codex(user_message="test"), "OK")

    @patch("ai_scientist.codex_cli.shutil.which", return_value="/usr/bin/codex")
    def test_invalid_reasoning_effort_fails_closed(self, _which):
        with patch.dict(
            "os.environ",
            {"AI_SCIENTIST_CODEX_REASONING_EFFORT": "impossible"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must be one of"):
                run_codex(user_message="test")


if __name__ == "__main__":
    unittest.main()
