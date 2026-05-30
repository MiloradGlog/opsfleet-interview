"""Runtime container: lazily wires the LLM, embeddings, BigQuery, Golden Bucket,
and the analysis subgraph from ``Settings``.

Lazy construction means the CLI starts (and report-management commands work) even
before any analytical call — and a missing credential surfaces only when the
feature that needs it is used.
"""
from __future__ import annotations

import logging
from typing import Any

from .bigquery_client import BigQueryRunner
from .config import Settings
from .golden_bucket import GoldenBucket, build_golden_bucket
from .schema_catalog import schema_for_prompt
from .storage import Storage
from .subgraph import AnalysisDeps, build_analysis_subgraph

log = logging.getLogger("retail_agent.runtime")


class AgentRuntime:
    def __init__(self, settings: Settings, thread_id: str) -> None:
        self.settings = settings
        self.thread_id = thread_id
        self.user_id = settings.user_id
        self.schema = schema_for_prompt()
        self.storage = Storage(settings.sqlite_path, settings.hmac_secret)

        self._llm: Any | None = None
        self._embeddings: Any | None = None
        self._runner: BigQueryRunner | None = None
        self._golden: GoldenBucket | None = None
        self._subgraph: Any | None = None

    # --- lazy collaborators --------------------------------------------------
    @property
    def llm(self) -> Any:
        if self._llm is None:
            from langchain.chat_models import init_chat_model

            log.info("Initializing chat model %s", self.settings.gemini_model)
            self._llm = init_chat_model(
                self.settings.gemini_model, model_provider="google_genai"
            )
        return self._llm

    @property
    def embeddings(self) -> Any:
        if self._embeddings is None:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            log.info("Initializing embeddings %s", self.settings.embed_model)
            self._embeddings = GoogleGenerativeAIEmbeddings(model=self.settings.embed_model)
        return self._embeddings

    @property
    def runner(self) -> BigQueryRunner:
        if self._runner is None:
            self._runner = BigQueryRunner(project_id=self.settings.gcp_project)
        return self._runner

    @property
    def golden(self) -> GoldenBucket:
        if self._golden is None:
            self._golden = build_golden_bucket(self.settings, self.embeddings)
        return self._golden

    @property
    def subgraph(self) -> Any:
        if self._subgraph is None:
            deps = AnalysisDeps(
                retrieve=self.golden.retrieve,
                complete=self._complete,
                run_query=self.runner.execute_query,
                schema=self.schema,
                max_attempts=self.settings.max_sql_attempts,
                max_result_rows=self.settings.max_result_rows,
                preview_rows=self.settings.preview_rows,
            )
            self._subgraph = build_analysis_subgraph(deps)
        return self._subgraph

    # --- helpers -------------------------------------------------------------
    def _complete(self, prompt: str) -> str:
        """Single-shot text completion: prompt -> model text."""
        resp = self.llm.invoke(prompt)
        content = getattr(resp, "content", resp)
        if isinstance(content, list):  # some providers return content blocks
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
                else:
                    parts.append(str(block))
            content = "".join(parts)
        return str(content)

    def close(self) -> None:
        self.storage.close()
