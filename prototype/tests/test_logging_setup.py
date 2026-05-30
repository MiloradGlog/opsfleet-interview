"""Logging setup creates a log file and is idempotent."""
import logging

from retail_agent.logging_setup import setup_logging


def test_setup_logging_creates_file_and_is_idempotent(tmp_path):
    setup_logging(tmp_path)
    setup_logging(tmp_path)  # second call is a no-op, must not raise
    logging.getLogger("retail_agent.test").info("hello")
    assert (tmp_path / "agent.log").exists()
