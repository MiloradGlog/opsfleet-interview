"""BigQuery access layer.

The ``BigQueryRunner`` class is the assignment-provided client, used **verbatim**.
Jobs bill to the caller's project (``project_id``, set to ``opsfleettest`` from env)
and the service-account key is loaded by ``GOOGLE_APPLICATION_CREDENTIALS`` — no
custom auth code.

Around it we add only an *exception classifier* so the analysis subgraph can tell
a *semantic* SQL error (-> regenerate the query) apart from a *transient* failure
(-> let the agent's ToolRetryMiddleware retry the whole tool with backoff).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("retail_agent.bigquery")


# ---------------------------------------------------------------------------
# Provided client — verbatim from the assignment. Do not modify the contract.
# ---------------------------------------------------------------------------
class BigQueryRunner:
    """A lean BigQuery client for executing SQL queries and returning DataFrame results."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        dataset_id: Optional[str] = "bigquery-public-data.thelook_ecommerce",
    ) -> None:
        from google.cloud import bigquery

        logging.info("Initializing BigQuery client")
        try:
            # project_id is the BILLING project (opsfleettest); the dataset itself
            # lives under bigquery-public-data. Credentials come from ADC /
            # GOOGLE_APPLICATION_CREDENTIALS — no key material in code.
            self.client = bigquery.Client(project=project_id)
            self.dataset_id = dataset_id
            logging.info(f"BigQuery client initialized for dataset: {self.dataset_id}")
        except Exception as e:
            logging.error(f"Failed to initialize BigQuery client: {str(e)}")
            raise

    def execute_query(self, sql_query: str):
        """Execute a SQL query and return results as a pandas DataFrame."""
        try:
            logging.info("Executing BigQuery query")
            query_job = self.client.query(sql_query)
            df = query_job.result().to_dataframe()
            logging.info(f"Query completed successfully, returned {len(df)} rows")
            return df
        except Exception as e:
            logging.error(f"BigQuery execution failed: {str(e)}")
            raise

    def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        """Get schema information for a specific table."""
        try:
            table_ref = f"{self.dataset_id}.{table_name}"
            table = self.client.get_table(table_ref)
            return [
                {
                    "name": f.name,
                    "type": f.field_type,
                    "mode": f.mode,
                    "description": f.description or "",
                }
                for f in table.schema
            ]
        except Exception as e:
            logging.error(f"Failed to get schema for table {table_name}: {str(e)}")
            raise


# ---------------------------------------------------------------------------
# Exception classification (our thin addition) — the resilience tell.
# ---------------------------------------------------------------------------
try:  # google-api-core is a transitive dep of google-cloud-bigquery
    from google.api_core import exceptions as _gexc

    _TRANSIENT_TYPES: tuple[type[BaseException], ...] = (
        _gexc.ServiceUnavailable,      # 503
        _gexc.InternalServerError,     # 500
        _gexc.GatewayTimeout,          # 504
        _gexc.TooManyRequests,         # 429
        _gexc.DeadlineExceeded,
        _gexc.RetryError,
        ConnectionError,
        TimeoutError,
    )
    _SEMANTIC_TYPES: tuple[type[BaseException], ...] = (
        _gexc.BadRequest,              # 400 — malformed / invalid SQL
        _gexc.NotFound,                # 404 — unknown table/column
    )
except Exception:  # pragma: no cover - google libs always present in practice
    _gexc = None
    _TRANSIENT_TYPES = (ConnectionError, TimeoutError)
    _SEMANTIC_TYPES = ()


def is_transient_error(exc: BaseException) -> bool:
    """True if ``exc`` is a transient infrastructure failure worth retrying as-is.

    Semantic SQL errors (BadRequest/NotFound) are explicitly *not* transient — the
    subgraph routes those to query regeneration. Anything not clearly semantic and
    not clearly transient is treated as **semantic** (safer: regenerate rather than
    hammer a possibly-failing endpoint), except connection/timeout which are always
    transient.
    """
    if isinstance(exc, _SEMANTIC_TYPES):
        return False
    return isinstance(exc, _TRANSIENT_TYPES)
