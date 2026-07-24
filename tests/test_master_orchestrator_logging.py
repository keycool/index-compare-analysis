import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = REPO_ROOT / "orchestrator" / "main.py"


class MasterOrchestratorLoggingTest(unittest.TestCase):
    def test_subprocess_output_is_streamed_for_action_diagnostics(self):
        text = ORCHESTRATOR.read_text(encoding="utf-8")

        self.assertIn("def run_command_streaming(", text)
        self.assertIn("subprocess.Popen(", text)
        self.assertIn('step_env["PYTHONUNBUFFERED"] = "1"', text)
        self.assertIn("elapsed_seconds", text)
        self.assertIn("run_command_streaming(", text)


if __name__ == "__main__":
    unittest.main()
