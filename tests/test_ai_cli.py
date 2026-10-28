"""Unit tests for the ai_search CLI commands."""

import unittest
from unittest.mock import patch
from ai_search.cli import main


class TestAICLI(unittest.TestCase):
    """Test suite for CLI search and training execution."""

    @patch("sys.argv", ["cli.py", "search", "Route 9 Albany"])
    def test_cli_search(self):
        # Should execute successfully without unhandled exceptions
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)

    @patch("sys.argv", ["cli.py", "feedback", "--query", "Albany", "--type", "suggestions", "--selected", "Albany, NY"])
    def test_cli_feedback(self):
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)

    @patch("sys.argv", ["cli.py", "train", "--batch-size", "10"])
    def test_cli_train(self):
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)


if __name__ == "__main__":
    unittest.main()
