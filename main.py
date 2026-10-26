import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

INVENTORY = ("MIC-01", "MIC-02", "OSC-01", "MUL-01", "FUE-01")
RESERVATIONS_FILE = Path(__file__).with_name("reservations.json")
_RESERVATION_LOCK = Lock()
_LOGGER = logging.getLogger(__name__)

app = FastAPI(title="Laboratory Reservation System")


class ReservationRequest(BaseModel):
    requester: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    start: datetime
    end: datetime


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_reservations() -> list[dict[str, Any]]:
    try:
        with RESERVATIONS_FILE.open(encoding="utf-8") as file:
            reservations = json.load(file)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail="Could not read reservation storage."
        ) from exc

    if not isinstance(reservations, list):
        raise HTTPException(
            status_code=500, detail="Reservation storage has an invalid format."
        )
    return reservations


def _save_reservations(reservations: list[dict[str, Any]]) -> None:
    temporary_file = RESERVATIONS_FILE.with_name(
        f"{RESERVATIONS_FILE.name}.{uuid4().hex}.tmp"
    )
    try:
        RESERVATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary_file.write_text(
            json.dumps(reservations, indent=2), encoding="utf-8"
        )
        os.replace(temporary_file, RESERVATIONS_FILE)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail="Could not save reservation storage."
        ) from exc
    finally:
        try:
            temporary_file.unlink(missing_ok=True)
        except OSError as exc:
            _LOGGER.warning("Could not remove temporary reservation file: %s", exc)


def _reservation_times(reservation: dict[str, Any]) -> tuple[datetime, datetime]:
    try:
        start = datetime.fromisoformat(reservation["start"])
        end = datetime.fromisoformat(reservation["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail="Reservation storage has invalid dates."
        ) from exc
    return _as_utc(start), _as_utc(end)


def _validate_interval(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    normalized_start = _as_utc(start)
    normalized_end = _as_utc(end)
    if normalized_start >= normalized_end:
        raise HTTPException(
            status_code=422, detail="Reservation start must be before its end."
        )
    return normalized_start, normalized_end


def _has_conflict(
    reservations: list[dict[str, Any]],
    instrument_id: str,
    start: datetime,
    end: datetime,
) -> bool:
    for reservation in reservations:
        if (
            reservation.get("status") != "active"
            or reservation.get("instrument_id") != instrument_id
        ):
            continue
        existing_start, existing_end = _reservation_times(reservation)
        if start < existing_end and end > existing_start:
            return True
    return False


@app.get("/api/inventory")
def get_inventory() -> list[str]:
    return list(INVENTORY)


@app.get("/api/availability")
def get_availability(
    start: datetime,
    end: datetime,
    instrument_id: str | None = Query(default=None),
) -> dict[str, list[dict[str, str | bool]]]:
    normalized_start, normalized_end = _validate_interval(start, end)
    if instrument_id is not None and instrument_id not in INVENTORY:
        raise HTTPException(status_code=404, detail="Instrument not found.")

    reservations = _load_reservations()
    instruments = (instrument_id,) if instrument_id else INVENTORY
    return {
        "availability": [
            {
                "instrument_id": item,
                "available": not _has_conflict(
                    reservations, item, normalized_start, normalized_end
                ),
            }
            for item in instruments
        ]
    }


@app.post("/api/reservations", status_code=201)
def create_reservation(request: ReservationRequest) -> dict[str, Any]:
    requester = request.requester.strip()
    if not requester:
        raise HTTPException(status_code=422, detail="Requester cannot be empty.")
    if request.instrument_id not in INVENTORY:
        raise HTTPException(status_code=404, detail="Instrument not found.")

    start, end = _validate_interval(request.start, request.end)
    with _RESERVATION_LOCK:
        reservations = _load_reservations()
        if _has_conflict(reservations, request.instrument_id, start, end):
            raise HTTPException(
                status_code=409,
                detail="Instrument already has an active reservation in that interval.",
            )

        reservation = {
            "id": str(uuid4()),
            "requester": requester,
            "instrument_id": request.instrument_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": "active",
        }
        reservations.append(reservation)
        _save_reservations(reservations)
    return reservation


@app.patch("/api/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: str) -> dict[str, Any]:
    with _RESERVATION_LOCK:
        reservations = _load_reservations()
        for reservation in reservations:
            if reservation.get("id") == reservation_id:
                if reservation.get("status") == "active":
                    reservation["status"] = "cancelled"
                    _save_reservations(reservations)
                return reservation
    raise HTTPException(status_code=404, detail="Reservation not found.")


@app.get("/api/reservations")
def get_reservations() -> list[dict[str, Any]]:
    return _load_reservations()
