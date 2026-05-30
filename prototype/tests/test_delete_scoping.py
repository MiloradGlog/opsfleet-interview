"""Storage: ownership scoping, soft-delete, drift, and audit idempotency."""
import pytest

from retail_agent.storage import Storage


@pytest.fixture
def store(tmp_path):
    s = Storage(tmp_path / "t.sqlite", hmac_secret="test-secret")
    yield s
    s.close()


def test_preview_and_delete_are_owner_scoped(store):
    a1 = store.save_report("manager_a", "Acme Q1", "about client acme")
    store.save_report("manager_a", "Other", "unrelated")
    b1 = store.save_report("manager_b", "Acme for B", "client acme too")

    prev_a = store.preview_deletable("manager_a", "acme")
    assert prev_a["count"] == 1 and prev_a["ids"] == [a1]
    # manager_a cannot even see manager_b's matching report
    assert b1 not in prev_a["ids"]

    # manager_a deleting b1 has no effect (scoped by user_id)
    counts = store.soft_delete("manager_a", [b1])
    assert counts["deleted"] == 0
    assert store.preview_deletable("manager_b", "acme")["count"] == 1


def test_soft_delete_excludes_from_future_listings(store):
    rid = store.save_report("manager_a", "Temp", "delete me")
    assert len(store.list_reports("manager_a")) == 1
    counts = store.soft_delete("manager_a", [rid])
    assert counts["deleted"] == 1
    assert store.list_reports("manager_a") == []


def test_double_delete_reports_drift(store):
    rid = store.save_report("manager_a", "Once", "body")
    first = store.soft_delete("manager_a", [rid])
    assert first == {"requested": 1, "deleted": 1, "already_gone": 0}
    second = store.soft_delete("manager_a", [rid])
    assert second == {"requested": 1, "deleted": 0, "already_gone": 1}


def test_audit_is_idempotent_on_double_resume(store):
    rid = store.save_report("manager_a", "X", "body")
    op = store.op_id("manager_a", "thread-1", [rid])
    counts = store.soft_delete("manager_a", [rid])
    assert store.write_audit(op, "manager_a", "delete_reports", [rid], counts) is True
    # same op_id again (a double-resume) must not duplicate
    assert store.write_audit(op, "manager_a", "delete_reports", [rid], counts) is False
    n = store.conn.execute("SELECT COUNT(*) n FROM audit_log").fetchone()["n"]
    assert n == 1


def test_op_id_is_order_independent(store):
    assert store.op_id("u", "t", [3, 1, 2]) == store.op_id("u", "t", [1, 2, 3])
    assert store.op_id("u", "t", [1, 2]) != store.op_id("u", "t", [1, 3])
