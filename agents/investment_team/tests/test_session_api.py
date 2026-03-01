from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from investment_team.api import main as api_main

app = api_main.app


client = TestClient(app)


def test_start_session_uses_opaque_ids_and_pending_mfa() -> None:
    response = client.post(
        "/sessions/login",
        json={"platform": "tradingview", "credential": {"credential_id": "cred-ref-1"}},
    )

    assert response.status_code == 200
    payload = response.json()["session"]

    assert payload["platform"] == "tradingview"
    assert payload["credential_id"] == "cred-ref-1"
    assert payload["status"] == "pending_mfa"
    assert payload["session_id"].startswith("sess-")
    assert payload["session_material_id"] is None
    assert "password" not in payload
    assert payload["mfa_challenge"] is not None


def test_get_and_terminate_session_lifecycle() -> None:
    create_response = client.post(
        "/sessions/login",
        json={"platform": "quantconnect", "credential": {"credential_id": "cred-ref-2"}},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session"]["session_id"]

    status_response = client.get(f"/sessions/{session_id}")
    assert status_response.status_code == 200
    assert status_response.json()["session"]["status"] == "active"

    terminate_response = client.delete(f"/sessions/{session_id}")
    assert terminate_response.status_code == 200
    assert terminate_response.json() == {"session_id": session_id, "terminated": True}

    not_found_response = client.get(f"/sessions/{session_id}")
    assert not_found_response.status_code == 404


def test_expired_session_status_is_reported() -> None:
    create_response = client.post(
        "/sessions/login",
        json={"platform": "quantconnect", "credential": {"credential_id": "cred-ref-3"}},
    )
    assert create_response.status_code == 200

    session = create_response.json()["session"]
    session_id = session["session_id"]

    # Overwrite timestamps to force expiration.
    expired_time = (datetime.now(tz=timezone.utc) - timedelta(minutes=1)).isoformat()
    api_main._sessions[session_id].expires_at = expired_time

    status_response = client.get(f"/sessions/{session_id}")
    assert status_response.status_code == 200
    assert status_response.json()["session"]["status"] == "expired"


def test_tradingview_invalid_or_empty_mfa_code_stays_pending() -> None:
    for mfa_code in ["", "abcxyz", "12ab56", "12345"]:
        response = client.post(
            "/sessions/login",
            json={
                "platform": "tradingview",
                "credential": {"credential_id": "cred-ref-invalid"},
                "mfa_code": mfa_code,
            },
        )
        assert response.status_code == 200
        payload = response.json()["session"]
        assert payload["status"] == "pending_mfa"
        assert payload["session_material_id"] is None
        assert payload["mfa_challenge"] is not None


def test_tradingview_valid_mfa_code_activates_session() -> None:
    response = client.post(
        "/sessions/login",
        json={
            "platform": "tradingview",
            "credential": {"credential_id": "cred-ref-valid"},
            "mfa_code": "123456",
        },
    )
    assert response.status_code == 200
    payload = response.json()["session"]
    assert payload["status"] == "active"
    assert payload["session_material_id"].startswith("smat-")
    assert payload["mfa_challenge"] is None


def test_get_session_status_does_not_recreate_deleted_session_on_expiry_path() -> None:
    create_response = client.post(
        "/sessions/login",
        json={"platform": "quantconnect", "credential": {"credential_id": "cred-ref-4"}},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session"]["session_id"]

    expired_time = (datetime.now(tz=timezone.utc) - timedelta(minutes=1)).isoformat()
    api_main._sessions[session_id].expires_at = expired_time

    # Simulate a concurrent delete by removing under the lock before status read writes back.
    with api_main._lock:
        deleted = api_main._sessions.pop(session_id, None)
    assert deleted is not None

    status_response = client.get(f"/sessions/{session_id}")
    assert status_response.status_code == 404
    assert session_id not in api_main._sessions
