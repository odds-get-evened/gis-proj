"""Smoke test for the backend's lifecycle.

Starts the backend the same way the Electron app does, checks that it answers,
checks that the old /shutdown endpoint is gone, then closes its standard input
and checks that it exits cleanly.

Usage (from the repository root):
    python scripts/smoke_test_backend.py dist/gis-backend/gis-backend   # compiled backend
    python scripts/smoke_test_backend.py python main.py                 # from source
"""
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional

BASE_URL = "http://127.0.0.1:8000"


class BackendSmokeTest:
    def __init__(self, command: List[str], cwd: Optional[str] = None,
                 startup_timeout: float = 60, shutdown_timeout: float = 15):
        self.command = command + ["--stop-on-stdin-close"]
        self.cwd = cwd
        self.startup_timeout = startup_timeout
        self.shutdown_timeout = shutdown_timeout

    @staticmethod
    def is_port_in_use() -> bool:
        try:
            urllib.request.urlopen(f"{BASE_URL}/health", timeout=1)
            return True
        except (urllib.error.URLError, OSError):
            return False

    def run(self) -> None:
        """Raises AssertionError describing the first check that fails."""
        if self.is_port_in_use():
            raise AssertionError(f"Something is already answering on {BASE_URL}; stop it and retry")

        process = subprocess.Popen(self.command, cwd=self.cwd, stdin=subprocess.PIPE)
        try:
            self._wait_until_healthy(process)
            print("backend is healthy")
            self._assert_shutdown_endpoint_is_gone()
            print("/shutdown endpoint is gone")

            process.stdin.close()
            try:
                exit_code = process.wait(timeout=self.shutdown_timeout)
            except subprocess.TimeoutExpired:
                raise AssertionError(f"backend still running {self.shutdown_timeout}s after stdin closed")
            if exit_code != 0:
                raise AssertionError(f"backend exited with code {exit_code} after stdin closed")
            print("backend exited cleanly when stdin closed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def _wait_until_healthy(self, process: subprocess.Popen) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"backend exited during startup with code {process.returncode}")
            try:
                with urllib.request.urlopen(f"{BASE_URL}/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        raise AssertionError(f"backend did not become healthy within {self.startup_timeout}s")

    @staticmethod
    def _assert_shutdown_endpoint_is_gone() -> None:
        request = urllib.request.Request(f"{BASE_URL}/shutdown", method="POST")
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            if error.code in (404, 405):
                return
            raise AssertionError(f"POST /shutdown returned HTTP {error.code}; expected 404")
        raise AssertionError("POST /shutdown succeeded; it should no longer exist")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    try:
        BackendSmokeTest(sys.argv[1:]).run()
    except AssertionError as failure:
        sys.exit(f"SMOKE TEST FAILED: {failure}")
