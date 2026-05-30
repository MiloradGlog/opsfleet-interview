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


# --- advanced / adversarial cases ------------------------------------------

def test_allows_cte_referencing_allowed_table():
    sql = (
        f"WITH totals AS (SELECT order_id, SUM(sale_price) v FROM `{DS}.order_items` GROUP BY order_id) "
        f"SELECT AVG(v) avg_v FROM totals LIMIT 10"
    )
    out = sql_guard.validate(sql, max_rows=1000)
    assert "totals" in out.lower()  # CTE name preserved, not rejected


def test_cte_over_disallowed_table_is_rejected():
    sql = f"WITH x AS (SELECT * FROM `{DS}.distribution_centers`) SELECT * FROM x LIMIT 5"
    with pytest.raises(SQLGuardError):
        sql_guard.validate(sql, max_rows=1000)


def test_cte_shadowing_a_fake_base_table_is_rejected():
    # 'users' here is a CTE over no real table -> no allowed source -> rejected
    with pytest.raises(SQLGuardError):
        sql_guard.validate("WITH users AS (SELECT 1 x) SELECT * FROM users LIMIT 5", max_rows=10)


def test_allows_union_of_allowed_tables_and_caps_limit():
    sql = (
        f"SELECT id FROM `{DS}.orders` UNION ALL SELECT id FROM `{DS}.order_items` LIMIT 5000"
    )
    out = sql_guard.validate(sql, max_rows=1000)
    assert "1000" in out and "5000" not in out


def test_subquery_in_from_over_allowed_table():
    sql = f"SELECT c FROM (SELECT category c FROM `{DS}.products`) AS s LIMIT 3"
    out = sql_guard.validate(sql, max_rows=1000)
    assert "products" in out.lower()


def test_rejects_information_schema():
    sql = f"SELECT table_name FROM `{DS}`.INFORMATION_SCHEMA.TABLES LIMIT 10"
    with pytest.raises(SQLGuardError):
        sql_guard.validate(sql, max_rows=1000)


def test_select_star_allowed_but_limited():
    out = sql_guard.validate(f"SELECT * FROM `{DS}.products`", max_rows=50)
    assert "limit 50" in out.lower().replace("\n", " ")


def test_disallowed_table_hidden_in_join_is_rejected():
    sql = (
        f"SELECT 1 FROM `{DS}.orders` o "
        f"JOIN `{DS}.inventory_items` i ON i.id = o.order_id LIMIT 5"
    )
    with pytest.raises(SQLGuardError):
        sql_guard.validate(sql, max_rows=1000)


def test_trailing_semicolon_is_tolerated():
    out = sql_guard.validate(f"SELECT id FROM `{DS}.orders` LIMIT 5;", max_rows=1000)
    assert "orders" in out.lower()
