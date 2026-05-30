"""Schema catalog: business-language description + SQL-grounding text."""
from retail_agent import schema_catalog as sc


def test_schema_for_prompt_lists_all_tables_and_dataset():
    text = sc.schema_for_prompt()
    for table in ("orders", "order_items", "products", "users"):
        assert table in text
    assert sc.DATASET_ID in text
    assert "sale_price" in text  # the revenue column the model must know


def test_describe_schema_focused_on_one_table():
    out = sc.describe_schema("products").lower()
    assert "products" in out and "category" in out and "brand" in out
    # focused: should not dump the full users column list
    assert "traffic_source" not in out


def test_describe_schema_unknown_topic_describes_everything():
    out = sc.describe_schema("zzz-not-a-table").lower()
    for table in ("orders", "order_items", "products", "users"):
        assert table in out


def test_describe_schema_flags_pii_columns():
    out = sc.describe_schema("users")
    assert "email" in out
    assert "sensitive personal data" in out.lower()


def test_qualified_name():
    assert sc.qualified("orders") == f"`{sc.DATASET_ID}.orders`"
