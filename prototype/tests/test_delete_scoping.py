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


def test_criteria_matches_title_or_body_case_insensitive(store):
    store.save_report("manager_a", "ACME Quarterly", "revenue summary")  # match in title
    store.save_report("manager_a", "Monthly recap", "notes about acme corp")  # match in body
    store.save_report("manager_a", "Widgets", "nothing relevant")
    prev = store.preview_deletable("manager_a", "AcMe")
    assert prev["count"] == 2


def test_empty_criteria_matches_all_owned(store):
    store.save_report("manager_a", "A", "x")
    store.save_report("manager_a", "B", "y")
    store.save_report("manager_b", "C", "z")
    prev = store.preview_deletable("manager_a", "")
    assert prev["count"] == 2  # both of manager_a's, none of manager_b's


def test_mixed_ownership_delete_only_removes_owned(store):
    a = store.save_report("manager_a", "mine", "x")
    b = store.save_report("manager_b", "theirs", "y")
    counts = store.soft_delete("manager_a", [a, b])
    assert counts["deleted"] == 1            # only the owned row
    assert len(store.list_reports("manager_b")) == 1  # other user's intact


def test_audit_counts_are_persisted_as_json(store):
    import json
    rid = store.save_report("manager_a", "X", "x")
    counts = store.soft_delete("manager_a", [rid])
    op = store.op_id("manager_a", "th", [rid])
    store.write_audit(op, "manager_a", "delete_reports", [rid], counts)
    row = store.conn.execute("SELECT target_ids, counts FROM audit_log WHERE op_id=?", (op,)).fetchone()
    assert json.loads(row["target_ids"]) == [rid]
    assert json.loads(row["counts"]) == counts
