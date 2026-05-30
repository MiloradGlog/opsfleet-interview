"""Read-only SQL guard tests."""
import pytest

from retail_agent import sql_guard
from retail_agent.sql_guard import SQLGuardError

DS = "bigquery-public-data.thelook_ecommerce"


def test_accepts_valid_select_and_keeps_limit():
    sql = f"SELECT category, COUNT(*) c FROM `{DS}.products` GROUP BY category LIMIT 10"
    out = sql_guard.validate(sql, max_rows=1000)
    assert "products" in out.lower()
    assert "limit" in out.lower()


def test_injects_limit_when_missing():
    sql = f"SELECT id FROM `{DS}.orders`"
    out = sql_guard.validate(sql, max_rows=500)
    assert "limit 500" in out.lower().replace("\n", " ")


def test_caps_oversized_limit():
    sql = f"SELECT id FROM `{DS}.orders` LIMIT 999999"
    out = sql_guard.validate(sql, max_rows=1000)
    assert "999999" not in out
    assert "1000" in out


@pytest.mark.parametrize("bad", [
    f"DELETE FROM `{DS}.orders`",
    f"UPDATE `{DS}.orders` SET status='x'",
    f"DROP TABLE `{DS}.orders`",
    f"INSERT INTO `{DS}.orders` (id) VALUES (1)",
    "CREATE TABLE foo (id INT)",
])
def test_rejects_dml_ddl(bad):
    with pytest.raises(SQLGuardError):
        sql_guard.validate(bad, max_rows=1000)


def test_rejects_disallowed_table():
    sql = f"SELECT * FROM `{DS}.inventory_items` LIMIT 5"
    with pytest.raises(SQLGuardError):
        sql_guard.validate(sql, max_rows=1000)


def test_rejects_multiple_statements():
    sql = f"SELECT 1 FROM `{DS}.orders`; SELECT 2 FROM `{DS}.users`"
    with pytest.raises(SQLGuardError):
        sql_guard.validate(sql, max_rows=1000)


def test_rejects_unparseable():
    with pytest.raises(SQLGuardError):
        sql_guard.validate("this is not sql", max_rows=1000)


def test_allows_join_across_allowed_tables():
    sql = (
        f"SELECT p.category, SUM(oi.sale_price) rev "
        f"FROM `{DS}.order_items` oi JOIN `{DS}.products` p ON oi.product_id = p.id "
        f"GROUP BY p.category LIMIT 25"
    )
    out = sql_guard.validate(sql, max_rows=1000)
    assert "order_items" in out.lower() and "products" in out.lower()
