"""High-Stakes Oversight (R3): ownership scoping, drift-safety, audit idempotency.

Uses the SQLite-backed FakePool so the exact Storage SQL (scoping + ON CONFLICT)
is exercised offline.
"""
from retail_agent.storage import Storage

from .fakes import FakePool


def _store():
    return Storage(FakePool(), hmac_secret="test-secret")


def test_cross_user_isolation_on_delete():
    s = _store()
    mine = s.save_report("manager_a", "Acme review", "about client acme")
    theirs = s.save_report("manager_b", "Acme review", "about client acme")

    # manager_a tries to delete both ids; only their own is affected.
    counts = s.soft_delete("manager_a", [mine, theirs])
    assert counts["deleted"] == 1

    # manager_b's report is still live.
    assert any(r["id"] == theirs for r in s.list_reports("manager_b"))


def test_preview_is_scoped_to_owner():
    s = _store()
    s.save_report("manager_a", "Acme", "client acme stuff")
    s.save_report("manager_b", "Acme", "client acme stuff")
    prev = s.preview_deletable("manager_a", "acme")
    assert prev["count"] == 1


def test_double_resume_is_idempotent_via_audit_op_id():
    s = _store()
    rid = s.save_report("manager_a", "x", "y")
    op_id = s.op_id("manager_a", "thread-1", [rid])

    # First delete + audit.
    s.soft_delete("manager_a", [rid])
    first = s.write_audit(op_id, "manager_a", "delete_reports", [rid], {"deleted": 1})
    # Second (double) resume: same op_id -> audit insert is a no-op.
    second = s.write_audit(op_id, "manager_a", "delete_reports", [rid], {"deleted": 0})
    assert first is True
    assert second is False


def test_op_id_is_order_independent():
    s = _store()
    assert s.op_id("u", "t", [3, 1, 2]) == s.op_id("u", "t", [1, 2, 3])


def test_drift_safe_already_gone_reported():
    s = _store()
    rid = s.save_report("manager_a", "x", "y")
    s.soft_delete("manager_a", [rid])           # delete once
    counts = s.soft_delete("manager_a", [rid])  # captured-id set re-applied after drift
    assert counts["deleted"] == 0
    assert counts["already_gone"] == 1
