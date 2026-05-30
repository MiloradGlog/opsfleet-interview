"""Business-language schema catalog for the four mandated tables.

Serves two purposes:
* :func:`describe_schema` answers schema-discovery questions in plain language
  with no SQL execution (brief "Expected Agent Capabilities" / FR-1.2.5).
* :func:`schema_for_prompt` produces a compact column listing that grounds SQL
  generation.

The catalog is static (the thelook_ecommerce schema is fixed for this dataset),
which keeps the CLI startable and the unit tests runnable offline. It can be
refreshed from the live ``BigQueryRunner.get_table_schema`` if desired.
"""
from __future__ import annotations

from .config import DATASET_ID

# table -> (one-line business description, [(column, type, business meaning)])
_CATALOG: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "orders": (
        "One row per customer order (the order header).",
        [
            ("order_id", "INTEGER", "Unique order identifier"),
            ("user_id", "INTEGER", "Customer who placed the order"),
            ("status", "STRING", "Order status (Complete, Shipped, Cancelled, Returned, Processing)"),
            ("gender", "STRING", "Gender recorded on the order"),
            ("created_at", "TIMESTAMP", "When the order was placed"),
            ("shipped_at", "TIMESTAMP", "When the order shipped"),
            ("delivered_at", "TIMESTAMP", "When the order was delivered"),
            ("returned_at", "TIMESTAMP", "When the order was returned, if any"),
            ("num_of_item", "INTEGER", "Number of items in the order"),
        ],
    ),
    "order_items": (
        "One row per item within an order — the grain for revenue analysis.",
        [
            ("id", "INTEGER", "Unique order-item identifier"),
            ("order_id", "INTEGER", "Parent order"),
            ("user_id", "INTEGER", "Customer"),
            ("product_id", "INTEGER", "Product purchased"),
            ("inventory_item_id", "INTEGER", "Specific inventory unit sold"),
            ("status", "STRING", "Item status"),
            ("sale_price", "FLOAT", "Price the item sold for (revenue)"),
            ("created_at", "TIMESTAMP", "When the item was ordered"),
            ("shipped_at", "TIMESTAMP", "When the item shipped"),
            ("delivered_at", "TIMESTAMP", "When the item was delivered"),
            ("returned_at", "TIMESTAMP", "When the item was returned, if any"),
        ],
    ),
    "products": (
        "Product catalog — one row per product.",
        [
            ("id", "INTEGER", "Unique product identifier"),
            ("name", "STRING", "Product name"),
            ("brand", "STRING", "Brand"),
            ("category", "STRING", "Product category"),
            ("department", "STRING", "Department (e.g. Men, Women)"),
            ("sku", "STRING", "Stock keeping unit"),
            ("cost", "FLOAT", "Cost to the company"),
            ("retail_price", "FLOAT", "List price"),
            ("distribution_center_id", "INTEGER", "Originating distribution center"),
        ],
    ),
    "users": (
        "Customer demographics — one row per customer.",
        [
            ("id", "INTEGER", "Unique customer identifier"),
            ("first_name", "STRING", "Given name (personal data)"),
            ("last_name", "STRING", "Family name (personal data)"),
            ("email", "STRING", "Email address (personal data)"),
            ("age", "INTEGER", "Customer age"),
            ("gender", "STRING", "Customer gender"),
            ("state", "STRING", "State / region"),
            ("city", "STRING", "City"),
            ("country", "STRING", "Country"),
            ("postal_code", "STRING", "Postal code"),
            ("traffic_source", "STRING", "Acquisition channel"),
            ("created_at", "TIMESTAMP", "When the customer account was created"),
        ],
    ),
}

# Columns that hold personal data. PII masking is out of scope for this prototype
# (see README), but describe_schema flags them so users know they are sensitive.
PII_COLUMNS: dict[str, set[str]] = {
    "users": {"first_name", "last_name", "email"},
}


def qualified(table: str) -> str:
    """Fully-qualified BigQuery table name."""
    return f"`{DATASET_ID}.{table}`"


def schema_for_prompt() -> str:
    """Compact schema listing used to ground SQL generation."""
    lines = [f"Dataset: {DATASET_ID} (read-only). Reference tables fully-qualified, e.g. {qualified('orders')}.", ""]
    for table, (desc, cols) in _CATALOG.items():
        col_str = ", ".join(f"{c} {t}" for c, t, _ in cols)
        lines.append(f"{table}: {desc}")
        lines.append(f"  columns: {col_str}")
    return "\n".join(lines)


def describe_schema(topic: str = "") -> str:
    """Business-language schema description, optionally filtered to one table/topic."""
    topic = (topic or "").strip().lower()
    tables = [t for t in _CATALOG if not topic or topic in t or topic in _CATALOG[t][0].lower()]
    if not tables:
        tables = list(_CATALOG)  # unknown topic -> describe everything

    out = ["Here is the retail data you can ask about:\n"]
    for table in tables:
        desc, cols = _CATALOG[table]
        out.append(f"**{table}** — {desc}")
        for col, ctype, meaning in cols:
            flag = "  (sensitive personal data)" if col in PII_COLUMNS.get(table, set()) else ""
            out.append(f"  - {col} ({ctype.lower()}): {meaning}{flag}")
        out.append("")
    out.append(
        "You can ask about customer behavior, product performance, revenue over time, "
        "and comparisons across categories or regions."
    )
    return "\n".join(out)
