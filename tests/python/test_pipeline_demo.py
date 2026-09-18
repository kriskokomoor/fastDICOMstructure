import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python" / "examples"))
import pipeline_demo  # noqa: E402


class PipelineAcceptanceTest(unittest.TestCase):
    def test_diagnostic_bearing_input_is_rejected_before_policy_or_persistence(self):
        truncated = pipeline_demo.build_untrusted_input()[:-1]
        with self.assertRaisesRegex(RuntimeError, "input rejected"):
            pipeline_demo.structural_parse_and_inspect(truncated)


if __name__ == "__main__":
    unittest.main()
