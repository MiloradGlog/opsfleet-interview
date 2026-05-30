"""Minimal structured logging (developer hygiene — not the Observability requirement).

Logs go to a file by default so they never clutter the chat UI; set
``RETAIL_AGENT_LOG_STDERR=1`` to also see them on stderr.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

_CONFIGURED = False


def setup_logging(data_dir: Path) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handlers: list[logging.Handler] = [logging.FileHandler(data_dir / "agent.log")]
    if os.getenv("RETAIL_AGENT_LOG_STDERR") == "1":
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=os.getenv("RETAIL_AGENT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        handlers=handlers,
        force=True,
    )
    _CONFIGURED = True
