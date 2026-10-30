"""CLI regression: optimization must not remove event submission."""
import json
import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def test_optimized_python_replay(self):
        completed = subprocess.run(
            [sys.executable, "-O", "-m", "rgd_cognition", "demo", "--events", "4"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["health"]["counters"]["processed"], 4)
        self.assertFalse(result["health"]["actuation_interface"])


if __name__ == "__main__":
    unittest.main()
