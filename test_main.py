import asyncio
import json

import httpx
import pytest

import main


class APIClient:
    def request(self, method, url, **kwargs):
        async def send_request():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(send_request())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RESERVATIONS_FILE", tmp_path / "reservations.json")
    return APIClient()


def reservation_payload(
    *,
    requester="Ana",
    instrument_id="MIC-01",
    start="2026-11-01T09:00:00Z",
    end="2026-11-01T10:00:00Z",
):
    return {
        "requester": requester,
        "instrument_id": instrument_id,
        "start": start,
        "end": end,
    }


def test_inventory_contains_all_preloaded_instruments(client):
    response = client.get("/api/inventory")

    assert response.status_code == 200
    assert response.json() == ["MIC-01", "MIC-02", "OSC-01", "MUL-01", "FUE-01"]


@pytest.mark.parametrize("requester", ["", "   "])
def test_reservation_rejects_empty_requester(client, requester):
    response = client.post(
        "/api/reservations", json=reservation_payload(requester=requester)
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-11-01T10:00:00Z", "2026-11-01T09:00:00Z"),
        ("2026-11-01T09:00:00Z", "2026-11-01T09:00:00Z"),
    ],
)
def test_reservation_requires_start_before_end(client, start, end):
    response = client.post(
        "/api/reservations",
        json=reservation_payload(start=start, end=end),
    )

    assert response.status_code == 422


def test_reservation_rejects_invalid_date(client):
    response = client.post(
        "/api/reservations",
        json=reservation_payload(start="not-a-date"),
    )

    assert response.status_code == 422


def test_reservation_rejects_unknown_instrument(client):
    response = client.post(
        "/api/reservations",
        json=reservation_payload(instrument_id="MIC-99"),
    )

    assert response.status_code == 404


def test_overlapping_active_reservation_is_rejected(client):
    first = client.post("/api/reservations", json=reservation_payload())
    overlapping = client.post(
        "/api/reservations",
        json=reservation_payload(
            requester="Luis",
            start="2026-11-01T09:30:00Z",
            end="2026-11-01T10:30:00Z",
        ),
    )

    assert first.status_code == 201
    assert overlapping.status_code == 409


def test_consecutive_reservations_are_allowed(client):
    first = client.post("/api/reservations", json=reservation_payload())
    next_reservation = client.post(
        "/api/reservations",
        json=reservation_payload(
            requester="Luis",
            start="2026-11-01T10:00:00Z",
            end="2026-11-01T11:00:00Z",
        ),
    )

    assert first.status_code == 201
    assert next_reservation.status_code == 201


def test_different_instruments_can_be_reserved_simultaneously(client):
    first = client.post("/api/reservations", json=reservation_payload())
    second = client.post(
        "/api/reservations",
        json=reservation_payload(instrument_id="OSC-01", requester="Luis"),
    )

    assert first.status_code == 201
    assert second.status_code == 201


def test_availability_reports_active_conflicts(client):
    client.post("/api/reservations", json=reservation_payload())

    response = client.get(
        "/api/availability",
        params={
            "start": "2026-11-01T09:30:00Z",
            "end": "2026-11-01T10:30:00Z",
        },
    )

    assert response.status_code == 200
    availability = {
        item["instrument_id"]: item["available"]
        for item in response.json()["availability"]
    }
    assert availability == {
        "MIC-01": False,
        "MIC-02": True,
        "OSC-01": True,
        "MUL-01": True,
        "FUE-01": True,
    }


def test_availability_validates_range_and_instrument(client):
    invalid_range = client.get(
        "/api/availability",
        params={
            "start": "2026-11-01T10:00:00Z",
            "end": "2026-11-01T09:00:00Z",
        },
    )
    unknown_instrument = client.get(
        "/api/availability",
        params={
            "start": "2026-11-01T09:00:00Z",
            "end": "2026-11-01T10:00:00Z",
            "instrument_id": "MIC-99",
        },
    )

    assert invalid_range.status_code == 422
    assert unknown_instrument.status_code == 404


def test_cancelled_reservation_persists_and_no_longer_blocks_unit(client, tmp_path):
    created = client.post("/api/reservations", json=reservation_payload())
    reservation_id = created.json()["id"]

    cancelled = client.patch(f"/api/reservations/{reservation_id}/cancel")
    repeated = client.patch(f"/api/reservations/{reservation_id}/cancel")
    replacement = client.post(
        "/api/reservations",
        json=reservation_payload(requester="Luis"),
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert repeated.json()["status"] == "cancelled"
    assert replacement.status_code == 201

    stored = json.loads((tmp_path / "reservations.json").read_text(encoding="utf-8"))
    assert len(stored) == 2
    assert stored[0]["id"] == reservation_id
    assert stored[0]["status"] == "cancelled"
    assert stored[1]["status"] == "active"


def test_cancel_unknown_reservation_returns_not_found(client):
    response = client.patch("/api/reservations/unknown-id/cancel")

    assert response.status_code == 404


def test_reservations_endpoint_lists_active_and_cancelled_records(client):
    created = client.post("/api/reservations", json=reservation_payload())
    client.patch(f"/api/reservations/{created.json()['id']}/cancel")
    active = client.post(
        "/api/reservations",
        json=reservation_payload(instrument_id="OSC-01"),
    )

    response = client.get("/api/reservations")

    assert response.status_code == 200
    records = response.json()
    assert len(records) == 2
    assert {record["status"] for record in records} == {"active", "cancelled"}
    assert active.json() in records


def test_reservations_are_loaded_after_client_restart(client):
    created = client.post("/api/reservations", json=reservation_payload())

    response = APIClient().get("/api/reservations")

    assert response.status_code == 200
    assert response.json() == [created.json()]
