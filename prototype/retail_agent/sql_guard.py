"""Read-only SQL guard.

``BigQueryRunner.execute_query`` has no built-in safety, so every generated query
passes through :func:`validate` before execution. The guard enforces, by parsing
the statement with sqlglot (never by regex):

* exactly one statement,
* it is a ``SELECT`` (optionally wrapped in CTEs / set-operations),
* no DML/DDL anywhere in the tree (INSERT/UPDATE/DELETE/DROP/CREATE/...),
* every referenced table is in the allow-list,
* a ``LIMIT`` is present and capped at ``max_rows``.

The structural read-only guarantee is the wall that contains a prompt-injected or
buggy model — defense that does not depend on the LLM behaving.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from .config import ALLOWED_TABLES

_DIALECT = "bigquery"

# Statement / clause node types that must never appear.
_FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Drop, exp.Create, exp.Alter, exp.TruncateTable,
    exp.Command,        # catch-all for things sqlglot doesn't model (GRANT, CALL, ...)
)


class SQLGuardError(ValueError):
    """Raised when a query violates the read-only / allow-list policy."""


def _strip(sql: str) -> str:
    return (sql or "").strip().rstrip(";").strip()


def validate(sql: str, allowed_tables: tuple[str, ...] = ALLOWED_TABLES, max_rows: int = 1000) -> str:
    """Validate and normalize ``sql``; return the safe, LIMIT-capped query string.

    Raises :class:`SQLGuardError` with a human-readable reason on any violation.
    """
    cleaned = _strip(sql)
    if not cleaned:
        raise SQLGuardError("Empty query.")

    try:
        statements = [s for s in sqlglot.parse(cleaned, read=_DIALECT) if s is not None]
    except Exception as exc:  # sqlglot.errors.ParseError and friends
        raise SQLGuardError(f"Could not parse SQL: {exc}") from exc

    if len(statements) != 1:
        raise SQLGuardError("Exactly one statement is allowed.")

    stmt = statements[0]

    # 1) Must be a read (SELECT / CTE-wrapped SELECT / UNION etc.).
    if not isinstance(stmt, (exp.Select, exp.Union, exp.Subquery)):
        raise SQLGuardError("Only SELECT queries are allowed.")

    # 2) No DML/DDL anywhere in the tree.
    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN):
            raise SQLGuardError(
                f"Statement type '{type(node).__name__}' is not permitted (read-only)."
            )

    # 3) Every referenced table must be in the allow-list. Names introduced by
    #    CTEs (WITH ... AS) are local aliases, not source tables, so exclude them.
    allowed = {t.lower() for t in allowed_tables}
    cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE) if c.alias_or_name}
    referenced = {t.name.lower() for t in stmt.find_all(exp.Table) if t.name} - cte_names
    if not referenced:
        raise SQLGuardError("Query references no known table.")
    illegal = referenced - allowed
    if illegal:
        raise SQLGuardError(
            f"Query references tables outside the allow-list: {sorted(illegal)}. "
            f"Allowed: {sorted(allowed)}."
        )

    # 4) Enforce a LIMIT, capped at max_rows.
    return _apply_limit(stmt, max_rows)


def _apply_limit(stmt: exp.Expression, max_rows: int) -> str:
    """Ensure the outer query has a LIMIT no greater than ``max_rows``."""
    # Select and Union both support .limit(); .limit() replaces any existing one,
    # so an oversized LIMIT is capped rather than left nested.
    if isinstance(stmt, (exp.Select, exp.Union)):
        existing = _limit_value(stmt.args.get("limit"))
        if existing is None or existing > max_rows:
            stmt = stmt.limit(max_rows)
        return stmt.sql(dialect=_DIALECT)

    # Bare subquery (rare): wrap so the cap applies to the whole result set.
    wrapped = sqlglot.parse_one(
        f"SELECT * FROM ({stmt.sql(dialect=_DIALECT)}) AS _capped LIMIT {max_rows}",
        read=_DIALECT,
    )
    return wrapped.sql(dialect=_DIALECT)


def _limit_value(limit_node: exp.Expression | None) -> int | None:
    if limit_node is None:
        return None
    try:
        return int(limit_node.expression.this)  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return None  # non-literal LIMIT (e.g. parameter) — treat as "unknown", re-cap
