import os
import sys
import unittest

from scripts.smoke_test_backend import BackendSmokeTest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BackendLifecycleTests(unittest.TestCase):
    """Runs the real backend (python main.py) as a subprocess, like the Electron app does."""

    def test_backend_stops_when_stdin_closes_and_has_no_shutdown_endpoint(self):
        if BackendSmokeTest.is_port_in_use():
            self.skipTest("a backend is already running on port 8000")
        BackendSmokeTest([sys.executable, "main.py"], cwd=REPO_ROOT, startup_timeout=30).run()


if __name__ == "__main__":
    unittest.main()
