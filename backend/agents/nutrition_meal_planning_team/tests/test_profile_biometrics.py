"""SPEC-002 integration tests: biometric / clinical / completeness endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shared_postgres import is_postgres_enabled

_agents_dir = Path(__file__).resolve().parent.parent.parent
if str(_agents_dir) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_agents_dir))

from nutrition_meal_planning_team.api.main import app  # noqa: E402

pytestmark = pytest.mark.skipif(
    not is_postgres_enabled(),
    reason="SPEC-002 biometric tables require Postgres.",
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# --- PATCH /biometrics ---------------------------------------------------


def test_patch_biometrics_records_log(client):
    client.put(
        "/profile/bp1",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    r = client.patch(
        "/profile/bp1/biometrics",
        json={
            "sex": "female",
            "age_years": 32,
            "height_cm": 168.0,
            "weight_kg": 64.5,
            "activity_level": "moderate",
        },
    )
    assert r.status_code == 200
    bio = r.json()["biometrics"]
    assert bio["sex"] == "female"
    assert bio["age_years"] == 32
    assert bio["height_cm"] == 168.0
    assert bio["weight_kg"] == 64.5
    assert bio["activity_level"] == "moderate"

    hist = client.get("/profile/bp1/biometrics/history").json()
    fields = {e["field"] for e in hist["entries"]}
    # Every changed field should log.
    assert {"sex", "age_years", "height_cm", "weight_kg", "activity_level"} <= fields


def test_patch_biometrics_imperial_coerced_to_metric(client):
    client.put(
        "/profile/bp2",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    r = client.patch(
        "/profile/bp2/biometrics",
        json={"height_ft": 5, "height_in": 10, "weight_lb": 150},
    )
    assert r.status_code == 200
    bio = r.json()["biometrics"]
    # 5'10" == 177.8 cm; 150 lb == ~68.04 kg
    assert bio["height_cm"] == pytest.approx(177.8, abs=1e-3)
    assert bio["weight_kg"] == pytest.approx(68.038855, abs=1e-3)


def test_patch_biometrics_rejects_implausible(client):
    client.put(
        "/profile/bp3",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    r = client.patch("/profile/bp3/biometrics", json={"weight_kg": 500})
    assert r.status_code == 422


def test_patch_biometrics_no_changes_leaves_history_empty(client):
    client.put(
        "/profile/bp4",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    # Same default sex / activity — no deltas.
    r = client.patch(
        "/profile/bp4/biometrics",
        json={"sex": "unspecified", "activity_level": "sedentary"},
    )
    assert r.status_code == 200
    hist = client.get("/profile/bp4/biometrics/history").json()
    assert hist["entries"] == []


def test_biometric_history_field_filter(client):
    client.put(
        "/profile/bp5",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    client.patch("/profile/bp5/biometrics", json={"weight_kg": 70.0})
    client.patch("/profile/bp5/biometrics", json={"weight_kg": 69.5})
    client.patch("/profile/bp5/biometrics", json={"weight_kg": 69.1})
    r = client.get("/profile/bp5/biometrics/history", params={"field": "weight_kg"})
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 3
    values = [e["value_numeric"] for e in entries]
    # newest first
    assert values == [69.1, 69.5, 70.0]


# --- PATCH /clinical -----------------------------------------------------


def test_patch_clinical_splits_known_and_freetext(client):
    client.put(
        "/profile/cli1",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    r = client.patch(
        "/profile/cli1/clinical",
        json={
            "conditions": ["hypertension", "grandma's curse"],
            "medications": ["warfarin", "some-supplement"],
            "reproductive_state": "none",
            "ed_history_flag": False,
        },
    )
    assert r.status_code == 200
    clinical = r.json()["clinical"]
    assert clinical["conditions"] == ["hypertension"]
    assert clinical["conditions_freetext"] == ["grandma's curse"]
    assert clinical["medications"] == ["warfarin"]
    assert clinical["medications_freetext"] == ["some-supplement"]


def test_patch_clinical_ed_flag_persists(client):
    client.put(
        "/profile/cli2",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    r = client.patch("/profile/cli2/clinical", json={"ed_history_flag": True})
    assert r.status_code == 200
    assert r.json()["clinical"]["ed_history_flag"] is True


# --- PUT /clinical-overrides ---------------------------------------------


def test_put_clinician_overrides_audits_changes(client):
    client.put(
        "/profile/co1",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    r1 = client.put(
        "/profile/co1/clinical-overrides",
        json={"overrides": {"bmi_floor": 19.5}, "reason": "dietitian guidance"},
    )
    assert r1.status_code == 200
    assert r1.json()["clinical"]["clinician_overrides"] == {"bmi_floor": 19.5}

    # Update with a new override; old one removed, new one added.
    r2 = client.put(
        "/profile/co1/clinical-overrides",
        json={"overrides": {"sodium_cap_mg": 1500.0}},
    )
    assert r2.status_code == 200
    assert r2.json()["clinical"]["clinician_overrides"] == {"sodium_cap_mg": 1500.0}


# --- GET /completeness ---------------------------------------------------


def test_completeness_unknown_client_returns_blockers(client):
    r = client.get("/profile/never-existed/completeness")
    assert r.status_code == 200
    body = r.json()
    assert "no_profile" in body["blockers"]
    assert "missing_sex" in body["blockers"]


def test_completeness_full_profile_has_no_blockers(client):
    client.put(
        "/profile/full1",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    client.patch(
        "/profile/full1/biometrics",
        json={
            "sex": "female",
            "age_years": 32,
            "height_cm": 168.0,
            "weight_kg": 64.5,
            "activity_level": "moderate",
        },
    )
    r = client.get("/profile/full1/completeness")
    body = r.json()
    assert body["has_biometrics"] is True
    assert body["has_activity"] is True
    assert body["is_minor"] is False
    assert body["blockers"] == []


def test_completeness_minor_flagged(client):
    client.put(
        "/profile/minor1",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    client.patch(
        "/profile/minor1/biometrics",
        json={
            "sex": "female",
            "age_years": 15,
            "height_cm": 160.0,
            "weight_kg": 50.0,
            "activity_level": "moderate",
        },
    )
    body = client.get("/profile/minor1/completeness").json()
    assert body["is_minor"] is True
    assert "minor_guidance_only" in body["blockers"]


def test_completeness_ed_flag_surfaces(client):
    client.put(
        "/profile/ed1",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    client.patch("/profile/ed1/clinical", json={"ed_history_flag": True})
    body = client.get("/profile/ed1/completeness").json()
    assert body["ed_history_flag"] is True
    assert body["has_clinical_confirmed"] is True


def test_completeness_partial_biometrics_reports_specific_blockers(client):
    client.put(
        "/profile/part1",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    # Only provide sex + age; no height/weight yet.
    client.patch(
        "/profile/part1/biometrics",
        json={"sex": "male", "age_years": 40},
    )
    body = client.get("/profile/part1/completeness").json()
    assert "missing_height_cm" in body["blockers"]
    assert "missing_weight_kg" in body["blockers"]
    assert "missing_sex" not in body["blockers"]
    assert "missing_age_years" not in body["blockers"]
    assert body["has_biometrics"] is False


# --- profile_version bump invariant --------------------------------------


def test_profile_version_increments_on_patches(client):
    client.put(
        "/profile/pv1",
        json={"household": {"number_of_people": 1, "description": "solo"}},
    )
    p1 = client.get("/profile/pv1").json()
    v1 = p1["profile_version"]

    client.patch("/profile/pv1/biometrics", json={"weight_kg": 70.0})
    p2 = client.get("/profile/pv1").json()
    assert p2["profile_version"] == v1 + 1

    client.patch("/profile/pv1/clinical", json={"ed_history_flag": True})
    p3 = client.get("/profile/pv1").json()
    assert p3["profile_version"] == v1 + 2
