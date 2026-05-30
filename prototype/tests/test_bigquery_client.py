"""Exception classifier that separates transient from semantic BigQuery errors."""
import pytest

from retail_agent.bigquery_client import is_transient_error

try:
    from google.api_core import exceptions as gexc
except Exception:  # pragma: no cover
    gexc = None


@pytest.mark.skipif(gexc is None, reason="google-api-core not available")
@pytest.mark.parametrize("exc", [
    lambda: gexc.ServiceUnavailable("503"),
    lambda: gexc.InternalServerError("500"),
    lambda: gexc.TooManyRequests("429"),
    lambda: gexc.GatewayTimeout("504"),
])
def test_google_transient_errors_are_transient(exc):
    assert is_transient_error(exc()) is True


@pytest.mark.skipif(gexc is None, reason="google-api-core not available")
@pytest.mark.parametrize("exc", [
    lambda: gexc.BadRequest("invalid SQL"),
    lambda: gexc.NotFound("no such table"),
])
def test_google_semantic_errors_are_not_transient(exc):
    assert is_transient_error(exc()) is False


def test_stdlib_connection_and_timeout_are_transient():
    assert is_transient_error(ConnectionError("reset")) is True
    assert is_transient_error(TimeoutError("slow")) is True


def test_unknown_error_defaults_to_semantic():
    # A plain error is treated as semantic (regenerate) rather than retried blindly.
    assert is_transient_error(ValueError("Unrecognized name: foo")) is False
    assert is_transient_error(Exception("???")) is False
