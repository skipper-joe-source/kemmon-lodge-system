"""Run against a dedicated, migrated test database only."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app, engine

pytestmark = pytest.mark.skipif(os.environ.get("KEMMON_TEST_DATABASE") != "1", reason="Dedicated test database required")
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_database():
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE reservations"))
        connection.execute(text("UPDATE rooms SET taken=false, nightly_rate=40000"))
    yield


def booking(**changes):
    return {"guest": "Test Guest", "phone": "+255700000000", "roomId": 1,
            "checkIn": "2026-12-01", "checkOut": "2026-12-03", **changes}


def test_save_list_cancel_and_rebook():
    response = client.post("/api/reservations", json=booking())
    assert response.status_code == 201
    row = response.json()
    assert row["nights"] == 2 and row["total"] == 80000
    assert client.get("/api/reservations").json() == [row]
    assert client.delete(f'/api/reservations/{row["id"]}').status_code == 204
    assert client.get("/api/reservations").json() == []
    with engine.connect() as connection:
        assert connection.execute(text("SELECT status FROM reservations WHERE id=:id"), {"id": row["id"]}).scalar() == "cancelled"
    assert client.post("/api/reservations", json=booking()).status_code == 201


def test_overlap_and_checkout_boundary():
    assert client.post("/api/reservations", json=booking()).status_code == 201
    assert client.post("/api/reservations", json=booking(checkIn="2026-12-02", checkOut="2026-12-04")).status_code == 409
    assert client.post("/api/reservations", json=booking(checkIn="2026-12-03", checkOut="2026-12-04")).status_code == 201
    assert client.post("/api/reservations", json=booking(roomId=2)).status_code == 201


@pytest.mark.parametrize("changes", [{"guest":"  "}, {"phone":" "}, {"roomId":12}, {"checkOut":"2026-12-01"}, {"checkOut":"2026-11-30"}])
def test_validation(changes):
    assert client.post("/api/reservations", json=booking(**changes)).status_code == 422


def test_taken_room_and_server_rate():
    assert client.patch("/api/rooms/1", json={"taken":True}).status_code == 200
    assert client.post("/api/reservations", json=booking()).status_code == 409
    client.patch("/api/rooms/1", json={"taken":False})
    assert client.post("/api/reservations", json=booking(total=1, nightly_rate=1)).json()["total"] == 80000


def test_concurrent_booking():
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post("/api/reservations", json=booking()), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]


def test_database_constraint_blocks_direct_overlap():
    from sqlalchemy.exc import IntegrityError
    client.post("/api/reservations", json=booking())
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("""INSERT INTO reservations (id,guest_name,phone,room_id,arrival_date,departure_date,nightly_rate)
                VALUES (:id,'Test','123',1,'2026-12-02','2026-12-04',40000)"""), {"id":uuid4()})
