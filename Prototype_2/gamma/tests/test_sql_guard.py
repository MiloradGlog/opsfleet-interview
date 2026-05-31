"""sql_guard — the densest-tested seam. Rejections must be by AST, not regex."""
import pytest

from retail_agent import sql_guard
from retail_agent.sql_guard import SQLGuardError, validate


def test_accepts_plain_select_and_enforces_limit():
    out = validate("SELECT * FROM orders", max_rows=1000)
    assert "limit" in out.lower()
    assert "1000" in out


def test_caps_oversized_limit():
    out = validate("SELECT * FROM orders LIMIT 999999", max_rows=1000)
    assert "1000" in out
    assert "999999" not in out


def test_preserves_small_limit():
    out = validate("SELECT * FROM orders LIMIT 5", max_rows=1000)
    assert "5" in out


@pytest.mark.parametrize(
    "bad",
    [
        "DELETE FROM orders",
        "UPDATE orders SET status='x'",
        "INSERT INTO orders VALUES (1)",
        "DROP TABLE orders",
        "CREATE TABLE x (a int)",
        "TRUNCATE TABLE orders",
        "GRANT SELECT ON orders TO bob",
    ],
)
def test_rejects_writes_and_ddl(bad):
    with pytest.raises(SQLGuardError):
        validate(bad)


def test_rejects_unknown_table():
    with pytest.raises(SQLGuardError) as e:
        validate("SELECT * FROM secret_admin_table LIMIT 10")
    assert "allow-list" in str(e.value)


def test_rejects_cte():
    with pytest.raises(SQLGuardError) as e:
        validate("WITH x AS (SELECT * FROM orders) SELECT * FROM x LIMIT 10")
    assert "CTE" in str(e.value) or "SELECT" in str(e.value)


def test_rejects_union():
    with pytest.raises(SQLGuardError):
        validate("SELECT id FROM orders UNION SELECT id FROM users LIMIT 10")


def test_rejects_multiple_statements():
    with pytest.raises(SQLGuardError):
        validate("SELECT * FROM orders; DROP TABLE orders")


def test_rejects_empty():
    with pytest.raises(SQLGuardError):
        validate("   ")


def test_rejects_injection_disguised_as_select():
    # A write hidden in a subquery is still caught by the AST walk.
    with pytest.raises(SQLGuardError):
        validate("SELECT * FROM orders WHERE id IN (DELETE FROM users RETURNING id)")


def test_allows_join_across_allowed_tables():
    out = validate(
        "SELECT p.name FROM order_items oi JOIN products p ON oi.product_id = p.id LIMIT 10"
    )
    assert "limit" in out.lower()
