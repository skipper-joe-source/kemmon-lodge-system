"""Local Kemmon reservation API backed by PostgreSQL."""

from datetime import date, datetime, timedelta, time
from decimal import Decimal
import hashlib
import json
import re
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from typing import Literal
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Depends, Request, Response, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError


class Settings(BaseSettings):
    database_url: str
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
    )


settings = Settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5},
)

SESSION_COOKIE = "kemmon_session"
SESSION_SECONDS = 8 * 60 * 60
password_hasher = PasswordHasher()
dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))


PERMISSION_CATALOG = {
    "reservations.edit": "Correct guest details, guest counts and pre-check-in dates",
    "alerts.view": "View alerts across financial, stock and room records",
    "alerts.review": "Mark owner alerts reviewed and add review notes",
    "audit.view": "View audit logs across all staff and operational records",
    "shifts.view": "View your own cashier shifts and closing reports",
    "shifts.manage": "Open and close your own cashier shift",
    "shifts.review": "Review all staff cashier shifts and shortages/surpluses",
    "bar.view": "View bar products, stock, sales reports and receipts",
    "bar.sell": "Record paid cash and mobile-money bar sales",
    "bar.charge": "Charge bar sales to checked-in guests' room bills",
    "bar.prices": "Set product selling prices",
    "inventory.view": "View products, stock levels and movement history",
    "inventory.manage": "Create inventory products and assign barcodes",
    "inventory.purchase": "Record stock purchases and supplier costs",
    "inventory.adjust": "Record wastage and reconcile physical stock counts",
    "maintenance.view": "View room maintenance issues and affected booking counts",
    "maintenance.manage": "Mark rooms out of service and complete repairs",
    "stays.transfer": "Transfer checked-in guests between rooms",
    "expenses.view": "View paid expense records",
    "expenses.record": "Record paid cash and mobile-money expenses",
    "cash.view": "View daily cash summaries and opening-cash history",
    "cash.manage": "Set or correct daily opening cash",
    "reservations.extend": "Extend reservation departure dates",
    "reports.view": "View collection reports, receipts, staff totals and outstanding balances",
    "rooms.view": "View rooms and current room status",
    "rooms.ready": "Mark cleaned rooms ready",
    "reservations.view": "View guest bookings, stay dates, costs and balances",
    "reservations.manage": "Create and cancel reservations",
    "stays.manage": "Check guests in and out",
    "payments.view": "View payment receipts and transaction references",
    "payments.record": "Record cash and mobile-money payments",
}
PERMISSION_DEPENDENCIES = {
    "reservations.edit": {"reservations.view"},
    "alerts.review": {"alerts.view"},
    "shifts.manage": {"shifts.view"},
    "shifts.review": {"shifts.view"},
    "bar.sell": {"bar.view", "shifts.manage"},
    "bar.charge": {"bar.sell"},
    "bar.prices": {"bar.view"},
    "inventory.manage": {"inventory.view"},
    "inventory.purchase": {"inventory.view"},
    "inventory.adjust": {"inventory.view"},
    "maintenance.view": {"rooms.view"},
    "maintenance.manage": {"maintenance.view"},
    "stays.transfer": {"reservations.view"},
    "expenses.record": {"expenses.view", "shifts.manage"},
    "cash.manage": {"cash.view"},
    "reservations.extend": {"reservations.view"},
    "rooms.ready": {"rooms.view"},
    "reservations.view": {"rooms.view"},
    "reservations.manage": {"reservations.view"},
    "stays.manage": {"reservations.view"},
    "payments.view": {"reservations.view"},
    "payments.record": {"payments.view", "shifts.manage"},
}


def normalize_permissions(values):
    result = set(values)
    unknown = result - PERMISSION_CATALOG.keys()
    if unknown:
        raise ValueError("Unknown permission: " + ", ".join(sorted(unknown)))
    while True:
        expanded = result | set().union(*(PERMISSION_DEPENDENCIES.get(value, set()) for value in result))
        if expanded == result:
            return sorted(result)
        result = expanded


def public_user(row):
    owner = row["role"] == "owner"
    return {
        "id": str(row["id"]), "username": row["username"], "role": row["role"],
        "isOwner": owner, "roleId": str(row["role_id"]) if row["role_id"] else None,
        "roleName": "Owner" if owner else row.get("role_name") or "Unassigned",
        "permissions": sorted(PERMISSION_CATALOG) if owner else row.get("role_permissions") or [],
        "isActive": row["is_active"],
    }


def user_with_role(connection, user_id):
    return connection.execute(text("""
        SELECT users.*, roles.name AS role_name, roles.permissions AS role_permissions
        FROM users LEFT JOIN roles ON roles.id=users.role_id WHERE users.id=:id
    """), {"id": user_id}).mappings().one()


def public_role(row):
    return {"id": str(row["id"]), "name": row["name"], "permissions": row["permissions"]}


def session_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def require_access(request: Request):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        allowed = {value.strip() for value in settings.allowed_origins.split(",")}
        allowed.add(str(request.base_url).rstrip("/"))
        if (origin and origin not in allowed) or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "This request origin is not allowed.")
    path = request.url.path
    if path in ("/api/health", "/api/auth/login", "/api/auth/logout"):
        return
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > 256:
        raise HTTPException(401, "Please log in.")
    with engine.connect() as connection:
        user = connection.execute(text("""
            SELECT users.*, roles.name AS role_name, roles.permissions AS role_permissions
            FROM staff_sessions JOIN users ON users.id=staff_sessions.user_id
            LEFT JOIN roles ON roles.id=users.role_id
            WHERE staff_sessions.token_hash=:token
              AND staff_sessions.expires_at > now() AND users.is_active=true
        """), {"token": session_digest(token)}).mappings().first()
    if user is None:
        raise HTTPException(401, "Your session ended. Please log in again.")
    request.state.user = dict(user)
    if user["role"] == "owner":
        return
    if path.startswith("/api/staff") or path.startswith("/api/roles") or path == "/api/permissions":
        raise HTTPException(403, "Only the owner can manage staff and roles.")
    if path in ("/api/auth/me", "/api/auth/password"):
        return
    method = request.method
    if method == "GET" and re.fullmatch(r"/api/receipts/[^/]+", path):
        if not {"payments.view", "reports.view"}.intersection(user["role_permissions"] or []):
            raise HTTPException(403, "Your role does not have permission to view payment receipts.")
        return
    required = None
    if method=="GET" and re.fullmatch(r"/api/reservations/[^/]+/edits",path):
        required={"reservations.view"}
    elif method=="POST" and re.fullmatch(r"/api/reservations/[^/]+/(edit|edit-preview)",path):
        required={"reservations.edit"}
    elif path=="/api/alerts/settings" and method=="POST":
        raise HTTPException(403,"Only the owner can change alert thresholds")
    elif method=="GET" and path in ("/api/alerts","/api/alerts/summary","/api/alerts/settings","/api/alerts/reviews"):
        required={"alerts.view"}
    elif method=="POST" and path=="/api/alerts/review":
        required={"alerts.review"}
    elif method == "GET" and path in ("/api/audit","/api/audit/options"):
        required={"audit.view"}
    elif method == "GET" and (path in ("/api/shifts","/api/shifts/current") or re.fullmatch(r"/api/shifts/[0-9a-fA-F-]+",path)):
        required={"shifts.view"}
    elif method == "POST" and (path=="/api/shifts" or re.fullmatch(r"/api/shifts/[^/]+/close",path)):
        required={"shifts.manage"}
    elif method == "GET" and path=="/api/bar/report":
        if not {"bar.view","reports.view"}.intersection(user["role_permissions"] or []):
            raise HTTPException(403,"Your role cannot view bar reports")
        return
    elif method == "POST" and re.fullmatch(r"/api/inventory/products/[^/]+/barcode",path):
        required={"inventory.manage"}
    elif method == "GET" and path=="/api/bar/scan":
        required={"bar.sell"}
    elif method == "GET" and path=="/api/bar/guests":
        required={"bar.charge"}
    elif method == "GET" and (path=="/api/bar/products" or re.fullmatch(r"/api/bar/sales/[^/]+",path)):
        required={"bar.view"}
    elif method == "POST" and path=="/api/bar/sales":
        required={"bar.sell"}
    elif method == "POST" and re.fullmatch(r"/api/bar/products/[^/]+/price",path):
        required={"bar.prices"}
    elif method == "GET" and re.fullmatch(r"/api/reservations/[^/]+/bar-sales",path):
        required={"payments.view"}
    elif method == "GET" and path in ("/api/inventory/products", "/api/inventory/movements"):
        required={"inventory.view"}
    elif method == "POST" and path=="/api/inventory/products":
        required={"inventory.manage"}
    elif method == "POST" and path=="/api/inventory/movements":
        if not {"inventory.purchase", "inventory.adjust"}.intersection(user["role_permissions"] or []):
            raise HTTPException(403,"Your role cannot record stock movements")
        return
    elif method == "GET" and path=="/api/maintenance":
        required={"maintenance.view"}
    elif method=="POST" and (path=="/api/maintenance" or re.fullmatch(r"/api/maintenance/[^/]+/resolve",path)):
        required={"maintenance.manage"}
    elif method == "POST" and re.fullmatch(r"/api/reservations/[^/]+/transfer", path):
        required = {"stays.transfer"}
    elif method == "GET" and re.fullmatch(r"/api/reservations/[^/]+/transfer-options", path):
        required = {"stays.transfer"}
    elif method == "GET" and re.fullmatch(r"/api/reservations/[^/]+/transfers", path):
        required = {"reservations.view"}
    elif path == "/api/expenses" and method in ("GET","POST"):
        required = {"expenses.view" if method=="GET" else "expenses.record"}
    elif path == "/api/cash/summary" and method=="GET":
        required = {"cash.view"}
    elif path == "/api/cash/opening" and method=="POST":
        required = {"cash.manage"}
    elif method == "POST" and re.fullmatch(r"/api/reservations/[^/]+/extend", path):
        required = {"reservations.extend"}
    elif method == "GET" and re.fullmatch(r"/api/reservations/[^/]+/extensions", path):
        required = {"reservations.view"}
    elif method == "GET" and path == "/api/reports/collections":
        required = {"reports.view"}
    elif method == "GET" and path == "/api/rooms":
        required = {"rooms.view"}
    elif method == "POST" and re.fullmatch(r"/api/rooms/\d+/ready", path):
        required = {"rooms.ready"}
    elif method == "GET" and path == "/api/reservations":
        required = {"reservations.view"}
    elif (method == "POST" and path == "/api/reservations") or (method == "DELETE" and re.fullmatch(r"/api/reservations/[^/]+", path)):
        required = {"reservations.manage"}
    elif method == "POST" and re.fullmatch(r"/api/reservations/[^/]+/check-(in|out)", path):
        required = {"stays.manage"}
    elif method == "POST" and path == "/api/walk-ins":
        required = {"reservations.manage", "stays.manage"}
    elif re.fullmatch(r"/api/reservations/[^/]+/payments", path):
        required = {"payments.view"} if method == "GET" else {"payments.record"} if method == "POST" else None
    permissions = set(user["role_permissions"] or [])
    if required is None or not required.issubset(permissions):
        raise HTTPException(403, "Your role does not have permission for this action. Contact the owner.")


def audit_staff(connection, owner_id, staff_id, action):
    connection.execute(text("""
        INSERT INTO staff_audit (id, owner_id, staff_id, action)
        VALUES (:id, :owner, :staff, :action)
    """), {"id": uuid4(), "owner": owner_id, "staff": staff_id, "action": action})


app = FastAPI(title="Kemmon Lodge API", dependencies=[Depends(require_access)])


@app.middleware("http")
async def private_api_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response



class Booking(BaseModel):
    guest: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    guestCount: int = Field(default=1, ge=1, le=100, strict=True)
    roomId: int = Field(ge=1, le=12)
    checkIn: date
    checkOut: date

    @field_validator("guest", "phone")
    @classmethod
    def trim_required(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("This field must not be blank")

        return value

    @model_validator(mode="after")
    def valid_stay(self):
        if self.checkOut < self.checkIn:
            raise ValueError("Checkout must be on or after the check-in date")

        return self


class RoomStatus(BaseModel):
    taken: bool


def room_response(row):
    return {
        "id": row["id"],
        "name": f'Room {row["room_number"]}',
        "roomNumber": row["room_number"],
        "price": int(row["nightly_rate"]),
        "taken": row["taken"],
        "cleaningStatus": row["cleaning_status"],
        "maintenanceStatus": row["maintenance_status"],
    }


def booking_response(row, connection=None):
    nights = (row["departure_date"] - row["arrival_date"]).days
    # A same-day stay is charged one full agreed room rate.
    billable_units = max(1, nights)
    total = int(row["nightly_rate"]) * billable_units + int(row["billing_adjustment"])
    room_total = total
    total += int(row["bar_charges"])
    paid = int(row.get("paid", 0))
    if connection is not None:
        paid = int(connection.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE reservation_id=:id"),
            {"id": row["id"]},
        ).scalar_one())

    maintenance_status=row.get("room_maintenance_status")
    if maintenance_status is None and connection is not None:
        maintenance_status=connection.execute(text("SELECT maintenance_status FROM rooms WHERE id=:id"),{"id":row["room_id"]}).scalar_one()
    return {
        "id": str(row["id"]),
        "roomOutOfService": maintenance_status=="out_of_service", "guest": row["guest_name"],
        "phone": row["phone"], "guestCount": row["guest_count"],
        "roomId": row["room_id"],
        "roomNumber": row["room_number"],
        "roomAllocationFrom": row["room_allocated_from"].isoformat(),
        "checkIn": row["arrival_date"].isoformat(),
        "checkOut": row["departure_date"].isoformat(),
        "nights": nights,
        "total": total, "roomTotal": room_total, "barCharges": int(row["bar_charges"]),
        "nightlyRate": int(row["nightly_rate"]),
        "paid": paid,
        "balance": max(0,total - paid),
        "credit": max(0,paid - total),
        "paymentStatus": "Credit due" if paid > total else "Paid" if paid == total else "Part paid" if paid > 0 else "Unpaid",
        "billableUnits": billable_units,
        "sameDay": nights == 0,
        "status": row["status"],
        "checkedInAt": row["checked_in_at"].isoformat() if row["checked_in_at"] else None,
        "checkedOutAt": row["checked_out_at"].isoformat() if row["checked_out_at"] else None,
    }


@app.exception_handler(OperationalError)
async def database_unavailable(request, exception):
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Database unavailable. Check PostgreSQL "
                "and backend configuration."
            )
        },
    )


@app.get("/api/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "postgresql",
    }


@app.get("/api/rooms")
def list_rooms():
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, room_number, nightly_rate, taken, cleaning_status, maintenance_status "
                "FROM rooms ORDER BY room_number"
            )
        ).mappings()

        return [room_response(row) for row in rows]


@app.patch("/api/rooms/{room_id}")
def update_room(room_id: int, body: RoomStatus):
    """Legacy manual occupancy adjustment; active stays cannot be overridden."""
    with engine.begin() as connection:
        room = connection.execute(
            text("SELECT * FROM rooms WHERE id=:id FOR UPDATE"), {"id": room_id}
        ).mappings().first()
        if room is None:
            raise HTTPException(404, "Room not found")
        active = connection.execute(
            text("SELECT id FROM reservations WHERE room_id=:id AND status='checked_in'"),
            {"id": room_id},
        ).first()
        if active:
            raise HTTPException(409, "Use the reservation's Check out action for an occupied room.")
        if body.taken and room["maintenance_status"]!="available":
            raise HTTPException(409,"This room is out of service")
        if body.taken and room["cleaning_status"] != "ready":
            raise HTTPException(409, "Clean the room and mark it ready first.")
        row = connection.execute(
            text("UPDATE rooms SET taken=:taken WHERE id=:id RETURNING *"),
            {"id": room_id, "taken": body.taken},
        ).mappings().one()
        return room_response(row)


@app.post("/api/rooms/{room_id}/ready")
def mark_room_ready(room_id: int):
    with engine.begin() as connection:
        room = connection.execute(
            text("SELECT * FROM rooms WHERE id=:id FOR UPDATE"), {"id": room_id}
        ).mappings().first()
        if room is None:
            raise HTTPException(404, "Room not found")
        if room["maintenance_status"]!="available":
            raise HTTPException(409,"Complete repairs before marking this room ready")
        active = connection.execute(
            text("SELECT id FROM reservations WHERE room_id=:id AND status='checked_in'"),
            {"id": room_id},
        ).first()
        if room["taken"] or active:
            raise HTTPException(409, "An occupied room cannot be marked ready.")
        row = connection.execute(
            text("UPDATE rooms SET cleaning_status='ready' WHERE id=:id RETURNING *"),
            {"id": room_id},
        ).mappings().one()
        return room_response(row)


@app.get("/api/reservations")
def list_reservations():
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT reservations.*, rooms.room_number, rooms.maintenance_status AS room_maintenance_status, COALESCE(receipts.paid, 0) AS paid
                FROM reservations
                JOIN rooms ON rooms.id = reservations.room_id
                LEFT JOIN (
                    SELECT reservation_id, SUM(amount) AS paid
                    FROM payments GROUP BY reservation_id
                ) receipts ON receipts.reservation_id = reservations.id
                ORDER BY reservations.created_at, reservations.id
            """)
        ).mappings()

        return [booking_response(row) for row in rows]


@app.post("/api/reservations", status_code=201)
def create_reservation(body: Booking):
    try:
        with engine.begin() as connection:
            room = connection.execute(
                text("""
                    SELECT room_number, nightly_rate, taken, maintenance_status
                    FROM rooms
                    WHERE id = :id
                    FOR UPDATE
                """),
                {"id": body.roomId},
            ).mappings().first()

            if room is None:
                raise HTTPException(404, "Room not found")

            if room["maintenance_status"]!="available":
                raise HTTPException(409,"This room is out of service and cannot accept new bookings")
            # Reservation dates are protected by PostgreSQL's overlap constraint.
            # Current occupancy does not block a booking for a future stay.
            row = connection.execute(
                text("""
                    INSERT INTO reservations (
                        id,
                        guest_name,
                        phone,
                        guest_count,
                        room_id,
                        arrival_date,
                        departure_date,
                        nightly_rate
                    )
                    VALUES (
                        :id,
                        :guest,
                        :phone,
                        :guest_count,
                        :room,
                        :arrival,
                        :departure,
                        :rate
                    )
                    RETURNING *
                """),
                {
                    "id": uuid4(),
                    "guest": body.guest,
                    "phone": body.phone, "guest_count": body.guestCount,
                    "room": body.roomId,
                    "arrival": body.checkIn,
                    "departure": body.checkOut,
                    "rate": room["nightly_rate"],
                },
            ).mappings().one()

            booking_row = dict(row)
            booking_row["room_number"] = room["room_number"]
            result = booking_response(booking_row, connection)

        return result

    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23P01":
            raise HTTPException(
                409,
                "This room already has a reservation during those dates.",
            ) from error

        raise


@app.delete("/api/reservations/{reservation_id}", status_code=204)
def cancel_reservation(reservation_id: UUID):
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT * FROM reservations WHERE id=:id FOR UPDATE"),
            {"id": reservation_id},
        ).mappings().first()
        if row is None or row["status"] != "confirmed":
            raise HTTPException(404, "Confirmed reservation not found")
        paid = connection.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE reservation_id=:id"),
            {"id": reservation_id},
        ).scalar_one()
        if paid:
            raise HTTPException(409, "This reservation has payments. A refund/correction workflow is needed before cancellation.")
        connection.execute(
            text("UPDATE reservations SET status='cancelled', cancelled_at=now() WHERE id=:id"),
            {"id": reservation_id},
        )


# Lock the room before the reservation so simultaneous actions serialize safely.
def lock_reservation_action(connection, reservation_id):
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id,0))"), {"id": str(reservation_id)})


def lock_stay(connection, reservation_id):
    lock_reservation_action(connection,reservation_id)
    room_id = connection.execute(
        text("SELECT room_id FROM reservations WHERE id=:id"),
        {"id": reservation_id},
    ).scalar_one_or_none()
    if room_id is None:
        raise HTTPException(404, "Reservation not found")
    room = connection.execute(
        text("SELECT * FROM rooms WHERE id=:id FOR UPDATE"), {"id": room_id}
    ).mappings().one()
    reservation = connection.execute(
        text("SELECT * FROM reservations WHERE id=:id FOR UPDATE"),
        {"id": reservation_id},
    ).mappings().one()
    return room, reservation


@app.post("/api/reservations/{reservation_id}/check-in")
def check_in(reservation_id: UUID):
    with engine.begin() as connection:
        room, reservation = lock_stay(connection, reservation_id)
        if reservation["status"] != "confirmed":
            raise HTTPException(409, "Only a confirmed reservation can be checked in.")
        if room["maintenance_status"]!="available":
            raise HTTPException(409,"This room is out of service. Resolve maintenance before check-in.")
        today = datetime.now(ZoneInfo("Africa/Dar_es_Salaam")).date()
        effective_departure = max(
            reservation["departure_date"], reservation["arrival_date"] + timedelta(days=1)
        )
        if not reservation["arrival_date"] <= today < effective_departure:
            raise HTTPException(409, "Check the reservation dates. Same-day guests can check in on their arrival date; overnight guests must arrive before departure.")
        active = connection.execute(
            text("SELECT id FROM reservations WHERE room_id=:id AND status='checked_in'"),
            {"id": room["id"]},
        ).first()
        if room["taken"] or active:
            raise HTTPException(409, "This room is already occupied.")
        if room["cleaning_status"] != "ready":
            raise HTTPException(409, "This room needs cleaning. Mark it ready before check-in.")
        row = connection.execute(
            text("UPDATE reservations SET status='checked_in', checked_in_at=now() WHERE id=:id RETURNING *"),
            {"id": reservation_id},
        ).mappings().one()
        connection.execute(text("UPDATE rooms SET taken=true WHERE id=:id"), {"id": room["id"]})
        result = dict(row)
        result["room_number"] = room["room_number"]
        return booking_response(result, connection)


@app.post("/api/reservations/{reservation_id}/check-out")
def check_out(reservation_id: UUID):
    with engine.begin() as connection:
        room, reservation = lock_stay(connection, reservation_id)
        if reservation["status"] != "checked_in":
            raise HTTPException(409, "Only a checked-in reservation can be checked out.")
        row = connection.execute(
            text("UPDATE reservations SET status='checked_out', checked_out_at=now() WHERE id=:id RETURNING *"),
            {"id": reservation_id},
        ).mappings().one()
        connection.execute(
            text("UPDATE rooms SET taken=false, cleaning_status='needs_cleaning' WHERE id=:id"),
            {"id": room["id"]},
        )
        result = dict(row)
        result["room_number"] = room["room_number"]
        return booking_response(result, connection)


class WalkIn(BaseModel):
    guest: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    guestCount: int = Field(default=1, ge=1, le=100, strict=True)
    roomId: int = Field(ge=1, le=12)
    checkOut: date

    @field_validator("guest", "phone")
    @classmethod
    def trim_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("This field must not be blank")
        return value


@app.post("/api/walk-ins", status_code=201)
def create_walk_in(body: WalkIn):
    """Save a walk-in booking and immediate check-in as one transaction."""
    today = datetime.now(ZoneInfo("Africa/Dar_es_Salaam")).date()
    if body.checkOut < today:
        raise HTTPException(422, "Departure must be today or a later date.")
    try:
        with engine.begin() as connection:
            room = connection.execute(
                text("SELECT * FROM rooms WHERE id=:id FOR UPDATE"),
                {"id": body.roomId},
            ).mappings().first()
            if room is None:
                raise HTTPException(404, "Room not found")
            if room["maintenance_status"]!="available":
                raise HTTPException(409,"This room is out of service and cannot accept walk-ins")
            active = connection.execute(
                text("SELECT id FROM reservations WHERE room_id=:id AND status='checked_in'"),
                {"id": body.roomId},
            ).first()
            if room["taken"] or active:
                raise HTTPException(409, "This room is already occupied. Choose another room.")
            if room["cleaning_status"] != "ready":
                raise HTTPException(409, "This room needs cleaning. Mark it ready before check-in.")
            row = connection.execute(
                text("""
                    INSERT INTO reservations (
                        id, guest_name, phone, guest_count, room_id, arrival_date,
                        departure_date, nightly_rate, status, checked_in_at
                    ) VALUES (
                        :id, :guest, :phone, :guest_count, :room, :arrival,
                        :departure, :rate, 'checked_in', now()
                    ) RETURNING *
                """),
                {
                    "id": uuid4(), "guest": body.guest, "phone": body.phone, "guest_count": body.guestCount,
                    "room": body.roomId, "arrival": today,
                    "departure": body.checkOut, "rate": room["nightly_rate"],
                },
            ).mappings().one()
            connection.execute(
                text("UPDATE rooms SET taken=true WHERE id=:id"), {"id": body.roomId}
            )
            result = dict(row)
            result["room_number"] = room["room_number"]
            result = booking_response(result, connection)
        return result
    except IntegrityError as error:
        code = getattr(error.orig, "sqlstate", None)
        if code == "23P01":
            raise HTTPException(409, "This room has a reservation overlapping the walk-in stay. Choose another room or an earlier departure.") from error
        if code == "23505":
            raise HTTPException(409, "This room is already occupied. Refresh and choose another room.") from error
        raise


class Payment(BaseModel):
    requestId: UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=0, allow_inf_nan=False)
    method: Literal["cash", "mobile_money"]
    reference: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def valid_reference(self):
        self.reference = (self.reference or "").strip().upper() or None
        if self.method == "mobile_money" and self.reference is None:
            raise ValueError("Enter the mobile-money transaction reference")
        if self.method == "cash" and self.reference is not None:
            raise ValueError("Cash payments do not use a transaction reference")
        return self


def payment_response(row):
    return {
        "id": str(row["id"]), "reservationId": str(row["reservation_id"]) if row["reservation_id"] else None,
        "amount": int(row["amount"]), "method": row["method"],
        "reference": row["reference"], "paidAt": row["created_at"].isoformat(),
        "roomNumberAtPayment": row.get("room_number_at_payment"),
        "receivedById": str(row["received_by"]) if row["received_by"] else None,
        "receivedBy": row.get("received_by_username") or "Not recorded",
    }


@app.get("/api/reservations/{reservation_id}/payments")
def list_payments(reservation_id: UUID):
    with engine.connect() as connection:
        reservation = connection.execute(
            text("SELECT reservations.*, rooms.room_number, rooms.maintenance_status AS room_maintenance_status FROM reservations JOIN rooms ON rooms.id=reservations.room_id WHERE reservations.id=:id"),
            {"id": reservation_id},
        ).mappings().first()
        if reservation is None:
            raise HTTPException(404, "Reservation not found")
        rows = connection.execute(
            text("SELECT payments.*, users.username AS received_by_username, snap.room_number AS room_number_at_payment FROM payments LEFT JOIN users ON users.id=payments.received_by LEFT JOIN payment_room_snapshots snap ON snap.payment_id=payments.id WHERE reservation_id=:id ORDER BY payments.created_at, payments.id"),
            {"id": reservation_id},
        ).mappings().all()
        receipt_rows = dict(reservation)
        receipt_rows["paid"] = sum(row["amount"] for row in rows)
        return {"reservation": booking_response(receipt_rows),
                "payments": [payment_response(row) for row in rows]}


@app.post("/api/reservations/{reservation_id}/payments")
def record_payment(reservation_id: UUID, body: Payment, request: Request):
    """Record money already received; this does not initiate a mobile transfer."""
    try:
        with engine.begin() as connection:
            reservation = connection.execute(
                text("SELECT reservations.*, rooms.room_number, rooms.maintenance_status AS room_maintenance_status FROM reservations JOIN rooms ON rooms.id=reservations.room_id WHERE reservations.id=:id FOR UPDATE OF reservations"),
                {"id": reservation_id},
            ).mappings().first()
            if reservation is None:
                raise HTTPException(404, "Reservation not found")
            # A retried request must return its original receipt, never charge twice.
            existing = connection.execute(
                text("SELECT payments.*, users.username AS received_by_username, snap.room_number AS room_number_at_payment FROM payments LEFT JOIN users ON users.id=payments.received_by LEFT JOIN payment_room_snapshots snap ON snap.payment_id=payments.id WHERE payments.id=:id"), {"id": body.requestId},
            ).mappings().first()
            if existing:
                if (existing["reservation_id"] != reservation_id or
                    existing["amount"] != body.amount or existing["method"] != body.method or
                    existing["reference"] != body.reference):
                    raise HTTPException(409, "This request ID was already used for different payment details.")
                return {"payment": payment_response(existing),
                        "reservation": booking_response(reservation, connection)}
            if reservation["status"] == "cancelled":
                raise HTTPException(409, "Cannot record payment for a cancelled reservation.")
            summary = booking_response(reservation, connection)
            if body.amount > summary["balance"]:
                raise HTTPException(409, f'Amount exceeds the remaining balance of TZS {summary["balance"]:,}.')
            row = connection.execute(
                text("""
                    INSERT INTO payments (id, reservation_id, amount, method, reference, received_by)
                    VALUES (:id, :reservation, :amount, :method, :reference, :received_by)
                    RETURNING *
                """),
                {"id": body.requestId, "reservation": reservation_id, "amount": body.amount,
                 "method": body.method, "reference": body.reference, "received_by": request.state.user["id"]},
            ).mappings().one()
            receipt = dict(row)
            receipt["received_by_username"] = request.state.user["username"]
            receipt["room_number_at_payment"] = connection.execute(text("SELECT room_number FROM payment_room_snapshots WHERE payment_id=:id"), {"id": row["id"]}).scalar_one()
            return {"payment": payment_response(receipt),
                    "reservation": booking_response(reservation, connection)}
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise HTTPException(409, "This payment request or mobile transaction reference has already been recorded. Check payment history before retrying.") from error
        raise


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class NewStaff(BaseModel):
    model_config = {"extra": "forbid"}
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    password: str = Field(min_length=12, max_length=1024)
    roleId: UUID

    @field_validator("password")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value


class StaffAccess(BaseModel):
    model_config = {"extra": "forbid"}
    roleId: UUID
    isActive: bool


class ChangePassword(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=1024)
    newPassword: str = Field(min_length=12, max_length=1024)

    @field_validator("newPassword")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value


@app.post("/api/auth/login")
def login(body: Login, request: Request, response: Response):
    username = body.username.strip().lower()
    bucket = session_digest(f'{request.client.host if request.client else "local"}|{username}')
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM login_limits WHERE window_started < now() - interval '15 minutes'"))
        attempts = connection.execute(text("""
            INSERT INTO login_limits (bucket) VALUES (:bucket)
            ON CONFLICT (bucket) DO UPDATE SET attempts=login_limits.attempts+1
            RETURNING attempts
        """), {"bucket": bucket}).scalar_one()
        user = connection.execute(text("SELECT * FROM users WHERE username=:name"), {"name": username}).mappings().first()
    if attempts > 5:
        raise HTTPException(429, "Too many login attempts. Wait 15 minutes and try again.")
    try:
        password_hasher.verify(user["password_hash"] if user else dummy_password_hash, body.password)
        valid = user is not None and user["is_active"]
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid:
        raise HTTPException(401, "Incorrect username or password, or this account is disabled.")
    token = secrets.token_urlsafe(32)
    with engine.begin() as connection:
        # Re-check access under a lock so disabling an account cannot race login.
        current = connection.execute(text("SELECT * FROM users WHERE id=:id FOR UPDATE"), {"id": user["id"]}).mappings().one()
        if not current["is_active"] or current["password_hash"] != user["password_hash"]:
            raise HTTPException(401, "Account access changed. Please log in again.")
        connection.execute(text("DELETE FROM staff_sessions WHERE expires_at <= now()"))
        connection.execute(text("""
            INSERT INTO staff_sessions (token_hash, user_id, expires_at)
            VALUES (:token, :user, now() + interval '8 hours')
        """), {"token": session_digest(token), "user": user["id"]})
        connection.execute(text("DELETE FROM login_limits WHERE bucket=:bucket"), {"bucket": bucket})
        result = public_user(user_with_role(connection, current["id"]))
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/api")
    return {"user": result}


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM staff_sessions WHERE token_hash=:token"), {"token": session_digest(token)})
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True,
                           secure=settings.cookie_secure, samesite="strict")


@app.get("/api/auth/me")
def current_user(request: Request):
    return {"user": public_user(request.state.user)}


@app.post("/api/auth/password", status_code=204)
def change_password(body: ChangePassword, request: Request, response: Response):
    new_hash = password_hasher.hash(body.newPassword)
    with engine.begin() as connection:
        user = connection.execute(text("SELECT * FROM users WHERE id=:id FOR UPDATE"), {"id": request.state.user["id"]}).mappings().one()
        try:
            password_hasher.verify(user["password_hash"], body.currentPassword)
        except (VerificationError, InvalidHashError):
            raise HTTPException(400, "Current password is incorrect.")
        connection.execute(text("UPDATE users SET password_hash=:hash WHERE id=:id"), {"hash": new_hash, "id": user["id"]})
        connection.execute(text("DELETE FROM staff_sessions WHERE user_id=:id"), {"id": user["id"]})
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True,
                           secure=settings.cookie_secure, samesite="strict")


class RoleDefinition(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=80)
    permissions: list[str] = Field(max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value or value.casefold() == "owner" or any(ord(char) < 32 for char in value):
            raise ValueError("Choose a role name other than Owner, without control characters")
        return value

    @field_validator("permissions")
    @classmethod
    def known_permissions(cls, value):
        return normalize_permissions(value)


@app.get("/api/permissions")
def list_permissions():
    return [{"key": key, "label": label, "requires": sorted(PERMISSION_DEPENDENCIES.get(key, set()))}
            for key, label in PERMISSION_CATALOG.items()]


@app.get("/api/roles")
def list_roles():
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM roles ORDER BY lower(name)")).mappings()
        return [public_role(row) for row in rows]


def save_role(body, request, role_id=None):
    try:
        with engine.begin() as connection:
            if role_id is None:
                role_id = uuid4()
                row = connection.execute(text("""
                    INSERT INTO roles (id, name, permissions, created_by)
                    VALUES (:id, :name, CAST(:permissions AS jsonb), :owner) RETURNING *
                """), {"id": role_id, "name": body.name, "permissions": json.dumps(body.permissions),
                       "owner": request.state.user["id"]}).mappings().one()
                action = "created"
            else:
                existing = connection.execute(text("SELECT * FROM roles WHERE id=:id FOR UPDATE"), {"id": role_id}).mappings().first()
                if existing is None:
                    raise HTTPException(404, "Role not found")
                row = connection.execute(text("""
                    UPDATE roles SET name=:name, permissions=CAST(:permissions AS jsonb)
                    WHERE id=:id RETURNING *
                """), {"id": role_id, "name": body.name, "permissions": json.dumps(body.permissions)}).mappings().one()
                connection.execute(text("DELETE FROM staff_sessions WHERE user_id IN (SELECT id FROM users WHERE role_id=:id)"), {"id": role_id})
                action = "updated"
            connection.execute(text("INSERT INTO role_audit (id,owner_id,role_id,action) VALUES (:id,:owner,:role,:action)"),
                               {"id": uuid4(), "owner": request.state.user["id"], "role": role_id, "action": action})
            return public_role(row)
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise HTTPException(409, "A role with this name already exists.") from error
        raise


@app.post("/api/roles", status_code=201)
def create_role(body: RoleDefinition, request: Request):
    return save_role(body, request)


@app.patch("/api/roles/{role_id}")
def update_role(role_id: UUID, body: RoleDefinition, request: Request):
    return save_role(body, request, role_id)


@app.get("/api/staff")
def list_staff():
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT users.*, roles.name AS role_name, roles.permissions AS role_permissions
            FROM users LEFT JOIN roles ON roles.id=users.role_id ORDER BY users.created_at, username
        """)).mappings()
        return [public_user(row) for row in rows]


@app.post("/api/staff", status_code=201)
def create_staff(body: NewStaff, request: Request):
    hashed = password_hasher.hash(body.password)
    try:
        with engine.begin() as connection:
            role = connection.execute(text("SELECT id FROM roles WHERE id=:id FOR SHARE"), {"id": body.roleId}).first()
            if role is None:
                raise HTTPException(422, "Choose an existing custom role.")
            staff_id = uuid4()
            connection.execute(text("""
                INSERT INTO users (id,username,password_hash,role,role_id)
                VALUES (:id,:username,:hash,'staff',:role)
            """), {"id": staff_id, "username": body.username, "hash": hashed, "role": body.roleId})
            audit_staff(connection, request.state.user["id"], staff_id, "created")
            return public_user(user_with_role(connection, staff_id))
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise HTTPException(409, "This username is already in use.") from error
        raise


@app.patch("/api/staff/{staff_id}")
def update_staff(staff_id: UUID, body: StaffAccess, request: Request):
    with engine.begin() as connection:
        user = connection.execute(text("SELECT * FROM users WHERE id=:id FOR UPDATE"), {"id": staff_id}).mappings().first()
        if user is None:
            raise HTTPException(404, "Staff account not found")
        if user["role"] == "owner":
            raise HTTPException(403, "The owner account cannot be disabled or changed here.")
        role = connection.execute(text("SELECT id FROM roles WHERE id=:id FOR SHARE"), {"id": body.roleId}).first()
        if role is None:
            raise HTTPException(422, "Choose an existing custom role.")
        connection.execute(text("UPDATE users SET role_id=:role,is_active=:active WHERE id=:id"),
                           {"role": body.roleId, "active": body.isActive, "id": staff_id})
        if user["role_id"] != body.roleId or user["is_active"] != body.isActive:
            connection.execute(text("DELETE FROM staff_sessions WHERE user_id=:id"), {"id": staff_id})
            audit_staff(connection, request.state.user["id"], staff_id, "access_changed")
        return public_user(user_with_role(connection, staff_id))


@app.get("/api/reports/collections")
def collections_report(
    start_date: date,
    end_date: date,
    page: int = Query(default=1, ge=1),
    debt_page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
):
    """Receipts by Tanzania payment date; debt is the current all-stay balance."""
    if start_date > end_date:
        raise HTTPException(422, "The end date must be on or after the start date.")
    if end_date == date.max:
        raise HTTPException(422, "Choose an end date before 31 December 9999.")
    zone = ZoneInfo("Africa/Dar_es_Salaam")
    start = datetime.combine(start_date, time.min, tzinfo=zone)
    stop = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
    params = {"start": start, "stop": stop, "limit": page_size,
              "offset": (page - 1) * page_size, "debt_offset": (debt_page - 1) * page_size}
    receipt_filter = "p.created_at >= :start AND p.created_at < :stop"
    debt_cte = """
        WITH receipts AS (
            SELECT reservation_id, SUM(amount) AS paid
            FROM payments GROUP BY reservation_id
        ), balances AS (
            SELECT r.id, r.guest_name, r.phone, r.status, r.arrival_date,
                   r.departure_date, rooms.room_number,
                   (r.nightly_rate * GREATEST(1, r.departure_date-r.arrival_date)+r.billing_adjustment+r.bar_charges) AS total,
                   COALESCE(receipts.paid,0) AS paid
            FROM reservations r JOIN rooms ON rooms.id=r.room_id
            LEFT JOIN receipts ON receipts.reservation_id=r.id
            WHERE r.status <> 'cancelled'
        )
    """
    # Keep totals and both detail lists on the same database snapshot.
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            as_of = connection.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
            totals = connection.execute(text(f"""
                SELECT COALESCE(SUM(p.amount) FILTER (WHERE p.method='cash'),0) AS cash,
                       COALESCE(SUM(p.amount) FILTER (WHERE p.method='mobile_money'),0) AS mobile,
                       COALESCE(SUM(p.amount),0) AS total, COUNT(*) AS count
                FROM collection_receipts p WHERE {receipt_filter}
            """), params).mappings().one()
            staff = connection.execute(text(f"""
                SELECT p.received_by, COALESCE(u.username,'Not recorded') AS username,
                       COALESCE(SUM(p.amount) FILTER (WHERE p.method='cash'),0) AS cash,
                       COALESCE(SUM(p.amount) FILTER (WHERE p.method='mobile_money'),0) AS mobile,
                       SUM(p.amount) AS total, COUNT(*) AS count
                FROM collection_receipts p LEFT JOIN users u ON u.id=p.received_by
                WHERE {receipt_filter}
                GROUP BY p.received_by, u.username
                ORDER BY total DESC, username, p.received_by NULLS LAST
            """), params).mappings().all()
            receipt_rows = connection.execute(text(f"""
                SELECT p.*, u.username AS received_by_username,
                       COALESCE(r.guest_name,'Bar customer') AS guest_name, COALESCE(snap.room_number,rooms.room_number) AS room_number
                FROM collection_receipts p LEFT JOIN reservations r ON r.id=p.reservation_id
                LEFT JOIN rooms ON rooms.id=r.room_id LEFT JOIN users u ON u.id=p.received_by
                LEFT JOIN payment_room_snapshots snap ON snap.payment_id=p.id
                WHERE {receipt_filter}
                ORDER BY p.created_at DESC, p.id DESC LIMIT :limit OFFSET :offset
            """), params).mappings().all()
            debt_totals = connection.execute(text(debt_cte + """
                SELECT COUNT(*) AS count, COALESCE(SUM(total-paid),0) AS balance
                FROM balances WHERE total > paid
            """)).mappings().one()
            debts = connection.execute(text(debt_cte + """
                SELECT * FROM balances WHERE total > paid
                ORDER BY arrival_date, room_number, id LIMIT :limit OFFSET :debt_offset
            """), params).mappings().all()
    return {
        "startDate": start_date.isoformat(), "endDate": end_date.isoformat(),
        "timezone": "Africa/Dar_es_Salaam", "asOf": as_of.isoformat(),
        "cash": int(totals["cash"]), "mobileMoney": int(totals["mobile"]),
        "total": int(totals["total"]), "receiptCount": totals["count"],
        "staff": [{"id": str(row["received_by"]) if row["received_by"] else None,
                   "username": row["username"], "cash": int(row["cash"]),
                   "mobileMoney": int(row["mobile"]), "total": int(row["total"]),
                   "receiptCount": row["count"]} for row in staff],
        "receipts": [{**payment_response(row), "guest": row["guest_name"],
                      "roomNumber": row["room_number"]} for row in receipt_rows],
        "page": page, "pageSize": page_size,
        "pageCount": max(1, (totals["count"] + page_size - 1) // page_size),
        "outstanding": {
            "asOf": as_of.isoformat(), "scope": "All non-cancelled reservations, as of now",
            "totalBalance": int(debt_totals["balance"]), "count": debt_totals["count"],
            "page": debt_page,
            "pageCount": max(1, (debt_totals["count"] + page_size - 1) // page_size),
            "reservations": [{"id": str(row["id"]), "guest": row["guest_name"],
                              "phone": row["phone"], "roomNumber": row["room_number"],
                              "status": row["status"], "checkIn": row["arrival_date"].isoformat(),
                              "checkOut": row["departure_date"].isoformat(),
                              "total": int(row["total"]), "paid": int(row["paid"]),
                              "balance": int(row["total"]-row["paid"])} for row in debts],
        },
    }


@app.get("/api/receipts/{payment_id}")
def guest_receipt(payment_id: UUID):
    """Reprint a recorded payment, with the current account balance labelled clearly."""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            issued_at = connection.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
            payment = connection.execute(text("""
                SELECT payments.*, users.username AS received_by_username, snap.room_number AS room_number_at_payment
                FROM payments LEFT JOIN users ON users.id=payments.received_by LEFT JOIN payment_room_snapshots snap ON snap.payment_id=payments.id
                WHERE payments.id=:id
            """), {"id": payment_id}).mappings().first()
            if payment is None:
                return bar_receipt(connection, payment_id)
            reservation = connection.execute(text("""
                SELECT reservations.*, rooms.room_number, rooms.maintenance_status AS room_maintenance_status
                FROM reservations JOIN rooms ON rooms.id=reservations.room_id
                WHERE reservations.id=:id
            """), {"id": payment["reservation_id"]}).mappings().one()
            return {
                "lodgeName": "Kemmon Lodge",
                "receiptNumber": f"KEMMON-{str(payment_id).upper()}",
                "issuedAt": issued_at.isoformat(), "timezone": "Africa/Dar_es_Salaam",
                "payment": payment_response(payment),
                "reservation": booking_response(reservation, connection),
            }


class ExtendStay(BaseModel):
    model_config = {"extra": "forbid"}
    requestId: UUID
    expectedCheckOut: date
    newCheckOut: date
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Enter a reason for the extension")
        return value

    @model_validator(mode="after")
    def later_departure(self):
        if self.newCheckOut <= self.expectedCheckOut:
            raise ValueError("Choose a departure date later than the current departure")
        return self


def extension_response(row):
    return {"id": str(row["id"]), "reservationId": str(row["reservation_id"]) if row["reservation_id"] else None,
            "oldCheckOut": row["old_departure"].isoformat(), "newCheckOut": row["new_departure"].isoformat(),
            "nightlyRate": int(row["nightly_rate"]), "oldTotal": int(row["old_total"]),
            "newTotal": int(row["new_total"]), "additionalCost": int(row["new_total"]-row["old_total"]),
            "reason": row["reason"], "changedBy": row["changed_by_username"],
            "changedAt": row["changed_at"].isoformat()}


@app.get("/api/reservations/{reservation_id}/extensions")
def extension_history(reservation_id: UUID):
    with engine.connect() as connection:
        exists = connection.execute(text("SELECT id FROM reservations WHERE id=:id"), {"id": reservation_id}).first()
        if exists is None:
            raise HTTPException(404, "Reservation not found")
        rows = connection.execute(text("""
            SELECT e.*, u.username AS changed_by_username
            FROM reservation_extensions e JOIN users u ON u.id=e.changed_by
            WHERE e.reservation_id=:id ORDER BY e.changed_at DESC, e.id
        """), {"id": reservation_id}).mappings()
        return [extension_response(row) for row in rows]


@app.post("/api/reservations/{reservation_id}/extend")
def extend_stay(reservation_id: UUID, body: ExtendStay, request: Request):
    try:
        with engine.begin() as connection:
            room, reservation = lock_stay(connection, reservation_id)
            existing = connection.execute(text("""
                SELECT e.*,u.username AS changed_by_username FROM reservation_extensions e
                JOIN users u ON u.id=e.changed_by WHERE e.id=:id
            """), {"id": body.requestId}).mappings().first()
            if existing:
                if (existing["reservation_id"] != reservation_id or
                    existing["old_departure"] != body.expectedCheckOut or
                    existing["new_departure"] != body.newCheckOut or existing["reason"] != body.reason):
                    raise HTTPException(409, "This extension request was already used with different details.")
                result = dict(reservation); result["room_number"] = room["room_number"]
                return {"reservation": booking_response(result, connection), "extension": extension_response(existing)}
            if reservation["status"] not in ("confirmed", "checked_in"):
                raise HTTPException(409, "Only booked or checked-in reservations can be extended.")
            if reservation["departure_date"] != body.expectedCheckOut:
                raise HTTPException(409, "This reservation changed since you opened it. Close this window, refresh reservations, and review the latest departure date.")
            if room["maintenance_status"]!="available":
                raise HTTPException(409,"This room is out of service. Resolve maintenance before extending this booking.")
            today = datetime.now(ZoneInfo("Africa/Dar_es_Salaam")).date()
            if body.newCheckOut < today:
                raise HTTPException(422, "The new departure cannot be in the past.")
            old_total = int(reservation["nightly_rate"]) * max(1, (reservation["departure_date"]-reservation["arrival_date"]).days) + int(reservation["billing_adjustment"]) + int(reservation["bar_charges"])
            new_total = int(reservation["nightly_rate"]) * max(1, (body.newCheckOut-reservation["arrival_date"]).days) + int(reservation["billing_adjustment"]) + int(reservation["bar_charges"])
            row = connection.execute(text("UPDATE reservations SET departure_date=:departure WHERE id=:id RETURNING *"),
                                     {"departure": body.newCheckOut, "id": reservation_id}).mappings().one()
            change = connection.execute(text("""
                INSERT INTO reservation_extensions (
                    id,reservation_id,changed_by,old_departure,new_departure,
                    nightly_rate,old_total,new_total,reason
                ) VALUES (:id,:reservation,:staff,:old,:new,:rate,:old_total,:new_total,:reason)
                RETURNING *
            """), {"id": body.requestId, "reservation": reservation_id, "staff": request.state.user["id"],
                   "old": reservation["departure_date"], "new": body.newCheckOut,
                   "rate": reservation["nightly_rate"], "old_total": old_total,
                   "new_total": new_total, "reason": body.reason}).mappings().one()
            change_row = dict(change); change_row["changed_by_username"] = request.state.user["username"]
            result = dict(row); result["room_number"] = room["room_number"]
            return {"reservation": booking_response(result, connection), "extension": extension_response(change_row)}
    except IntegrityError as error:
        code = getattr(error.orig, "sqlstate", None)
        if code == "23P01":
            raise HTTPException(409, "This extension conflicts with another booking for the room. Choose an earlier departure.") from error
        if code == "23505":
            raise HTTPException(409, "This extension request has already been used. Refresh and check the extension history.") from error
        raise


def quote_transfer(reservation, source, target, today):
    old_rate=int(reservation["nightly_rate"])
    new_rate=old_rate if source["nightly_rate"]==target["nightly_rate"] else int(target["nightly_rate"])
    units=max(1,(reservation["departure_date"]-reservation["arrival_date"]).days)
    remaining=max(1,(reservation["departure_date"]-today).days)
    old_total=old_rate*units+int(reservation["billing_adjustment"])+int(reservation["bar_charges"])
    new_total=old_total+(new_rate-old_rate)*remaining
    version=session_digest("|".join(str(value) for value in (
        reservation["id"],reservation["room_id"],reservation["departure_date"],reservation["status"],
        old_rate,reservation["billing_adjustment"],reservation["bar_charges"],source["nightly_rate"],target["id"],target["nightly_rate"],today)))
    return {"targetRoomId":target["id"],"roomNumber":target["room_number"],"usualRate":int(target["nightly_rate"]),
            "oldRate":old_rate,"newRate":new_rate,"remainingNights":remaining,"oldTotal":old_total,"newTotal":new_total,
            "priceChange":new_total-old_total,"quoteVersion":version}


@app.get("/api/reservations/{reservation_id}/transfer-options")
def transfer_options(reservation_id:UUID):
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            reservation=connection.execute(text("SELECT * FROM reservations WHERE id=:id"),{"id":reservation_id}).mappings().first()
            if reservation is None: raise HTTPException(404,"Reservation not found")
            if reservation["status"]!="checked_in": raise HTTPException(409,"Only checked-in guests can transfer rooms")
            today=datetime.now(ZoneInfo("Africa/Dar_es_Salaam")).date()
            if reservation["departure_date"]<today or (reservation["departure_date"]==today and reservation["arrival_date"]<today):
                raise HTTPException(409,"Extend this overnight stay before transferring on or after its departure date.")
            source=connection.execute(text("SELECT * FROM rooms WHERE id=:id"),{"id":reservation["room_id"]}).mappings().one()
            rooms=connection.execute(text("""
                SELECT rooms.* FROM rooms WHERE rooms.id<>:source AND taken=false AND cleaning_status='ready' AND maintenance_status='available'
                AND NOT EXISTS(SELECT 1 FROM reservations r WHERE r.room_id=rooms.id
                    AND r.status IN ('confirmed','checked_in')
                    AND daterange(r.room_allocated_from,GREATEST(r.departure_date,r.room_allocated_from+1),'[)')
                        && daterange(CAST(:today AS date),GREATEST(CAST(:departure AS date),CAST(:today AS date)+1),'[)'))
                ORDER BY room_number
            """),{"source":source["id"],"today":today,"departure":reservation["departure_date"]}).mappings().all()
            row=dict(reservation);row["room_number"]=source["room_number"]
            return {"reservation":booking_response(row,connection),"options":[quote_transfer(reservation,source,target,today) for target in rooms]}


class RoomTransfer(BaseModel):
    model_config = {"extra": "forbid"}
    requestId: UUID
    expectedRoomId: int = Field(ge=1, le=12)
    targetRoomId: int = Field(ge=1, le=12)
    quoteVersion: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value):
        if not value.strip():
            raise ValueError("Enter a reason")
        return value.strip()


def transfer_response(row):
    return {"id": str(row["id"]), "fromRoom": row["from_number"], "toRoom": row["to_number"],
            "oldRate": int(row["old_rate"]), "newRate": int(row["new_rate"]),
            "oldTotal": int(row["old_total"]), "newTotal": int(row["new_total"]),
            "priceChange": int(row["new_total"]-row["old_total"]), "reason": row["reason"],
            "changedBy": row["username"], "changedAt": row["changed_at"].isoformat()}


@app.get("/api/reservations/{reservation_id}/transfers")
def transfer_history(reservation_id: UUID):
    with engine.connect() as connection:
        if connection.execute(text("SELECT id FROM reservations WHERE id=:id"), {"id": reservation_id}).first() is None:
            raise HTTPException(404, "Reservation not found")
        rows = connection.execute(text("""
            SELECT t.*,a.room_number AS from_number,b.room_number AS to_number,u.username
            FROM room_transfers t JOIN rooms a ON a.id=t.from_room_id
            JOIN rooms b ON b.id=t.to_room_id JOIN users u ON u.id=t.changed_by
            WHERE t.reservation_id=:id ORDER BY t.changed_at DESC,t.id
        """), {"id": reservation_id}).mappings()
        return [transfer_response(row) for row in rows]


@app.post("/api/reservations/{reservation_id}/transfer")
def transfer_room(reservation_id: UUID, body: RoomTransfer, request: Request):
    try:
        with engine.begin() as connection:
            lock_reservation_action(connection, reservation_id)
            existing = connection.execute(text("""
                SELECT t.*,a.room_number AS from_number,b.room_number AS to_number,u.username
                FROM room_transfers t JOIN rooms a ON a.id=t.from_room_id
                JOIN rooms b ON b.id=t.to_room_id JOIN users u ON u.id=t.changed_by WHERE t.id=:id
            """), {"id": body.requestId}).mappings().first()
            if existing:
                if (existing["reservation_id"] != reservation_id or existing["from_room_id"] != body.expectedRoomId or
                    existing["to_room_id"] != body.targetRoomId or existing["reason"] != body.reason or existing["quote_version"] != body.quoteVersion):
                    raise HTTPException(409, "This transfer request was used with different details.")
                row = connection.execute(text("SELECT r.*,rooms.room_number FROM reservations r JOIN rooms ON rooms.id=r.room_id WHERE r.id=:id"), {"id": reservation_id}).mappings().one()
                return {"reservation": booking_response(row, connection), "transfer": transfer_response(existing)}
            source_id = connection.execute(text("SELECT room_id FROM reservations WHERE id=:id"), {"id": reservation_id}).scalar_one_or_none()
            if source_id is None:
                raise HTTPException(404, "Reservation not found")
            if source_id == body.targetRoomId:
                raise HTTPException(422, "Choose a different room")
            rooms = connection.execute(text("SELECT * FROM rooms WHERE id IN (:source,:target) ORDER BY id FOR UPDATE"), {"source": source_id, "target": body.targetRoomId}).mappings().all()
            lookup = {row["id"]: row for row in rooms}
            if body.targetRoomId not in lookup:
                raise HTTPException(404, "Target room not found")
            reservation = connection.execute(text("SELECT * FROM reservations WHERE id=:id FOR UPDATE"), {"id": reservation_id}).mappings().one()
            if reservation["room_id"] != body.expectedRoomId:
                raise HTTPException(409, "The room changed. Close this window and refresh reservations.")
            if reservation["status"] != "checked_in":
                raise HTTPException(409, "Only a checked-in guest can be transferred")
            today = datetime.now(ZoneInfo("Africa/Dar_es_Salaam")).date()
            if reservation["departure_date"] < today or (reservation["departure_date"] == today and reservation["arrival_date"] < today):
                raise HTTPException(409, "Extend this overnight stay before transferring on or after its departure date.")
            target, source = lookup[body.targetRoomId], lookup[source_id]
            active = connection.execute(text("SELECT id FROM reservations WHERE room_id=:id AND status='checked_in'"), {"id": body.targetRoomId}).first()
            if target["taken"] or active or target["cleaning_status"] != "ready" or target["maintenance_status"]!="available":
                raise HTTPException(409, "The target room must be free, clean and in service")
            quote = quote_transfer(reservation, source, target, today)
            if quote["quoteVersion"] != body.quoteVersion:
                raise HTTPException(409, "The stay or room price changed. Refresh the transfer preview before confirming.")
            old_rate, new_rate = quote["oldRate"], quote["newRate"]
            old_total, new_total = quote["oldTotal"], quote["newTotal"]
            units = max(1, (reservation["departure_date"]-reservation["arrival_date"]).days)
            adjustment = new_total-new_rate*units-int(reservation["bar_charges"])
            row = connection.execute(text("""
                UPDATE reservations SET room_id=:room,room_allocated_from=:today,
                    nightly_rate=:rate,billing_adjustment=:adjustment WHERE id=:id RETURNING *
            """), {"room": body.targetRoomId, "today": today, "rate": new_rate, "adjustment": adjustment, "id": reservation_id}).mappings().one()
            connection.execute(text("UPDATE rooms SET taken=false,cleaning_status='needs_cleaning' WHERE id=:id"), {"id": source_id})
            connection.execute(text("UPDATE rooms SET taken=true WHERE id=:id"), {"id": body.targetRoomId})
            change = connection.execute(text("""
                INSERT INTO room_transfers(id,reservation_id,from_room_id,to_room_id,quote_version,old_allocation_start,
                    transfer_date,old_rate,new_rate,old_total,new_total,reason,changed_by)
                VALUES (:id,:reservation,:source,:target,:quote,:old_start,:today,:old_rate,:new_rate,:old_total,:new_total,:reason,:staff) RETURNING *
            """), {"id": body.requestId,"reservation":reservation_id,"source":source_id,"target":body.targetRoomId,
                   "quote":body.quoteVersion,"old_start":reservation["room_allocated_from"],"today":today,"old_rate":old_rate,"new_rate":new_rate,
                   "old_total":old_total,"new_total":new_total,"reason":body.reason,"staff":request.state.user["id"]}).mappings().one()
            change = dict(change); change.update(from_number=source["room_number"],to_number=target["room_number"],username=request.state.user["username"])
            result = dict(row); result["room_number"] = target["room_number"]
            return {"reservation":booking_response(result,connection),"transfer":transfer_response(change)}
    except IntegrityError as error:
        code = getattr(error.orig,"sqlstate",None)
        if code == "23P01":
            raise HTTPException(409,"The target room has a conflicting reservation during the remaining stay.") from error
        if code == "23505":
            raise HTTPException(409,"The room or request is already in use. Refresh and review transfer history.") from error
        raise


class Expense(BaseModel):
    requestId: UUID
    paidOn: date
    category: str = Field(min_length=1,max_length=80)
    description: str = Field(min_length=1,max_length=500)
    amount: Decimal = Field(gt=0,max_digits=12,decimal_places=0,allow_inf_nan=False)
    method: Literal["cash","mobile_money"]
    reference: str | None = Field(default=None,max_length=120)

    @field_validator("category","description")
    @classmethod
    def text_required(cls,value):
        if not value.strip(): raise ValueError("This field cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def valid_expense(self):
        if self.paidOn > datetime.now(ZoneInfo("Africa/Dar_es_Salaam")).date():
            raise ValueError("Paid expenses cannot be dated in the future")
        self.reference = (self.reference or "").strip().upper() or None
        if self.method=="mobile_money" and not self.reference: raise ValueError("Enter the mobile-money transaction reference")
        if self.method=="cash" and self.reference: raise ValueError("Cash expenses do not use a mobile reference")
        return self


def expense_response(row):
    return {"id":str(row["id"]),"paidOn":row["paid_on"].isoformat(),"category":row["category"],
            "description":row["description"],"amount":int(row["amount"]),"method":row["method"],
            "reference":row["reference"],"recordedBy":row["username"],"recordedAt":row["recorded_at"].isoformat()}


@app.post("/api/expenses")
def record_expense(body: Expense,request: Request):
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"expense:"+str(body.requestId)})
            existing=connection.execute(text("SELECT e.*,u.username FROM expenses e JOIN users u ON u.id=e.recorded_by WHERE e.id=:id"),{"id":body.requestId}).mappings().first()
            if existing:
                expected=(body.paidOn,body.category,body.description,body.amount,body.method,body.reference)
                actual=tuple(existing[key] for key in ("paid_on","category","description","amount","method","reference"))
                if actual!=expected: raise HTTPException(409,"This expense request was used with different details")
                return expense_response(existing)
            row=connection.execute(text("""INSERT INTO expenses(id,paid_on,category,description,amount,method,reference,recorded_by)
                VALUES(:id,:day,:category,:description,:amount,:method,:reference,:staff) RETURNING *"""),
                {"id":body.requestId,"day":body.paidOn,"category":body.category,"description":body.description,
                 "amount":body.amount,"method":body.method,"reference":body.reference,"staff":request.state.user["id"]}).mappings().one()
            row=dict(row);row["username"]=request.state.user["username"]
            return expense_response(row)
    except IntegrityError as error:
        if getattr(error.orig,"sqlstate",None)=="23505": raise HTTPException(409,"This mobile-money expense reference is already recorded") from error
        raise


@app.get("/api/expenses")
def list_expenses(start_date:date,end_date:date,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100)):
    if start_date>end_date: raise HTTPException(422,"End date must be on or after start date")
    params={"start":start_date,"end":end_date,"limit":page_size,"offset":(page-1)*page_size}
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            totals=connection.execute(text("""SELECT count(*) AS count,COALESCE(SUM(amount),0) AS total,
                COALESCE(SUM(amount) FILTER(WHERE method='cash'),0) AS cash,
                COALESCE(SUM(amount) FILTER(WHERE method='mobile_money'),0) AS mobile
                FROM expenses WHERE paid_on BETWEEN :start AND :end"""),params).mappings().one()
            rows=connection.execute(text("""SELECT e.*,u.username FROM expenses e JOIN users u ON u.id=e.recorded_by
                WHERE e.paid_on BETWEEN :start AND :end ORDER BY e.paid_on DESC,e.recorded_at DESC,e.id LIMIT :limit OFFSET :offset"""),params).mappings().all()
    return {"startDate":start_date.isoformat(),"endDate":end_date.isoformat(),"total":int(totals["total"]),
            "cash":int(totals["cash"]),"mobileMoney":int(totals["mobile"]),"count":totals["count"],"page":page,
            "pageCount":max(1,(totals["count"]+page_size-1)//page_size),"expenses":[expense_response(row) for row in rows]}


class OpeningCash(BaseModel):
    requestId:UUID
    day:date
    amount:Decimal=Field(ge=0,max_digits=12,decimal_places=0,allow_inf_nan=False)
    expectedAmount:Decimal | None=Field(default=None,ge=0,max_digits=12,decimal_places=0,allow_inf_nan=False)
    reason:str=Field(min_length=1,max_length=500)

    @field_validator("reason")
    @classmethod
    def reason_required(cls,value):
        if not value.strip(): raise ValueError("Enter a reason for setting or correcting opening cash")
        return value.strip()


def save_opening_cash(body:OpeningCash,request:Request):
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(20261019,:day)"),{"day":body.day.toordinal()})
        previous=connection.execute(text("SELECT * FROM opening_cash_changes WHERE id=:id"),{"id":body.requestId}).mappings().first()
        if previous:
            if (previous["day"]!=body.day or previous["amount"]!=body.amount or previous["previous_amount"]!=body.expectedAmount or previous["reason"]!=body.reason):
                raise HTTPException(409,"This opening-cash request was used with different details")
            return {"saved":True}
        current=connection.execute(text("SELECT amount FROM daily_opening_cash WHERE day=:day FOR UPDATE"),{"day":body.day}).scalar_one_or_none()
        if current!=body.expectedAmount: raise HTTPException(409,"Opening cash changed. Refresh the cash summary before saving.")
        connection.execute(text("""INSERT INTO daily_opening_cash(day,amount,recorded_by) VALUES(:day,:amount,:staff)
            ON CONFLICT(day) DO UPDATE SET amount=EXCLUDED.amount,recorded_by=EXCLUDED.recorded_by,recorded_at=now()"""),
            {"day":body.day,"amount":body.amount,"staff":request.state.user["id"]})
        connection.execute(text("""INSERT INTO opening_cash_changes(id,day,previous_amount,amount,reason,changed_by)
            VALUES(:id,:day,:previous,:amount,:reason,:staff)"""),
            {"id":body.requestId,"day":body.day,"previous":current,"amount":body.amount,"reason":body.reason,"staff":request.state.user["id"]})
        return {"saved":True}


@app.get("/api/cash/summary")
def daily_cash_summary(day:date):
    if day==date.max: raise HTTPException(422,"Choose an earlier date")
    zone=ZoneInfo("Africa/Dar_es_Salaam")
    params={"day":day,"start":datetime.combine(day,time.min,tzinfo=zone),"stop":datetime.combine(day+timedelta(days=1),time.min,tzinfo=zone)}
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            collected=connection.execute(text("""SELECT COALESCE(SUM(amount) FILTER(WHERE method='cash'),0) AS cash,
                COALESCE(SUM(amount) FILTER(WHERE method='mobile_money'),0) AS mobile
                FROM collection_receipts WHERE created_at>=:start AND created_at<:stop"""),params).mappings().one()
            spent=connection.execute(text("""SELECT COALESCE(SUM(amount) FILTER(WHERE method='cash'),0) AS cash,
                COALESCE(SUM(amount) FILTER(WHERE method='mobile_money'),0) AS mobile FROM expenses WHERE paid_on=:day"""),params).mappings().one()
            opening=connection.execute(text("SELECT amount FROM daily_opening_cash WHERE day=:day"),params).scalar_one_or_none()
            changes=connection.execute(text("""SELECT c.*,u.username FROM opening_cash_changes c JOIN users u ON u.id=c.changed_by
                WHERE c.day=:day ORDER BY c.changed_at DESC,c.id"""),params).mappings().all()
    movement=int(collected["cash"]-spent["cash"])
    return {"day":day.isoformat(),"openingCash":int(opening) if opening is not None else None,
            "cashCollected":int(collected["cash"]),"cashExpenses":int(spent["cash"]),"cashMovement":movement,
            "expectedCash":int(opening)+movement if opening is not None else None,
            "mobileCollected":int(collected["mobile"]),"mobileExpenses":int(spent["mobile"]),
            "mobileMovement":int(collected["mobile"]-spent["mobile"]),
            "changes":[{"id":str(row["id"]),"previousAmount":int(row["previous_amount"]) if row["previous_amount"] is not None else None,
                        "amount":int(row["amount"]),"reason":row["reason"],"changedBy":row["username"],"changedAt":row["changed_at"].isoformat()} for row in changes]}


@app.post("/api/cash/opening")
def set_opening_cash(body:OpeningCash,request:Request):
    try:
        return save_opening_cash(body,request)
    except IntegrityError as error:
        if getattr(error.orig,"sqlstate",None)=="23505":
            raise HTTPException(409,"This opening-cash request was already used. Refresh the summary.") from error
        raise


class MaintenanceIssue(BaseModel):
    requestId:UUID
    roomId:int=Field(ge=1,le=12)
    title:str=Field(min_length=1,max_length=200)
    description:str=Field(min_length=1,max_length=1000)

    @field_validator("title","description")
    @classmethod
    def text_required(cls,value):
        if not value.strip(): raise ValueError("This field cannot be blank")
        return value.strip()


class ResolveMaintenance(BaseModel):
    requestId:UUID
    notes:str=Field(min_length=1,max_length=1000)

    @field_validator("notes")
    @classmethod
    def notes_required(cls,value):
        if not value.strip(): raise ValueError("Describe the repairs completed")
        return value.strip()


def maintenance_response(connection,issue_id):
    row=connection.execute(text("""
        SELECT m.*,rooms.room_number,u.username AS reported_username,v.username AS resolved_username,
            (SELECT count(*) FROM reservations r WHERE r.room_id=m.room_id AND r.status='confirmed'
             AND GREATEST(r.departure_date,r.room_allocated_from+1)>:today) AS affected
        FROM maintenance_issues m JOIN rooms ON rooms.id=m.room_id
        JOIN users u ON u.id=m.reported_by LEFT JOIN users v ON v.id=m.resolved_by WHERE m.id=:id
    """),{"id":issue_id,"today":datetime.now(ZoneInfo("Africa/Dar_es_Salaam")).date()}).mappings().one()
    return {"id":str(row["id"]),"roomId":row["room_id"],"roomNumber":row["room_number"],
            "title":row["title"],"description":row["description"],"reportedBy":row["reported_username"],
            "reportedAt":row["reported_at"].isoformat(),"resolvedAt":row["resolved_at"].isoformat() if row["resolved_at"] else None,
            "resolvedBy":row["resolved_username"],"resolutionNotes":row["resolution_notes"],
            "affectedBookings":row["affected"] if row["resolved_at"] is None else 0}


@app.get("/api/maintenance")
def list_maintenance(state:Literal["open","resolved","all"]="open",page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100)):
    condition={"open":"resolved_at IS NULL","resolved":"resolved_at IS NOT NULL","all":"true"}[state]
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            count=connection.execute(text(f"SELECT count(*) FROM maintenance_issues WHERE {condition}")).scalar_one()
            ids=connection.execute(text(f"SELECT id FROM maintenance_issues WHERE {condition} ORDER BY reported_at DESC,id LIMIT :limit OFFSET :offset"),{"limit":page_size,"offset":(page-1)*page_size}).scalars().all()
            rows=[maintenance_response(connection,issue_id) for issue_id in ids]
    return {"issues":rows,"count":count,"page":page,"pageCount":max(1,(count+page_size-1)//page_size),"state":state}


@app.post("/api/maintenance")
def report_maintenance(body:MaintenanceIssue,request:Request):
    try:
        with engine.begin() as connection:
            room=connection.execute(text("SELECT * FROM rooms WHERE id=:id FOR UPDATE"),{"id":body.roomId}).mappings().first()
            if room is None: raise HTTPException(404,"Room not found")
            previous=connection.execute(text("SELECT * FROM maintenance_issues WHERE id=:id"),{"id":body.requestId}).mappings().first()
            if previous:
                if (previous["room_id"],previous["title"],previous["description"])!=(body.roomId,body.title,body.description):
                    raise HTTPException(409,"This request was already used for different maintenance details")
                return maintenance_response(connection,previous["id"])
            active=connection.execute(text("SELECT id FROM reservations WHERE room_id=:id AND status='checked_in'"),{"id":body.roomId}).first()
            if room["taken"] or active: raise HTTPException(409,"Transfer or check out the guest before marking this room out of service")
            issue=connection.execute(text("SELECT id FROM maintenance_issues WHERE room_id=:id AND resolved_at IS NULL"),{"id":body.roomId}).first()
            if issue: raise HTTPException(409,"This room already has an open maintenance issue")
            connection.execute(text("""INSERT INTO maintenance_issues(id,room_id,title,description,reported_by)
                VALUES(:id,:room,:title,:description,:staff)"""),{"id":body.requestId,"room":body.roomId,"title":body.title,"description":body.description,"staff":request.state.user["id"]})
            connection.execute(text("UPDATE rooms SET maintenance_status='out_of_service' WHERE id=:id"),{"id":body.roomId})
            connection.execute(text("INSERT INTO maintenance_events(id,issue_id,action,notes,actor_id) VALUES(:id,:id,'reported',:notes,:staff)"),{"id":body.requestId,"notes":body.description,"staff":request.state.user["id"]})
            return maintenance_response(connection,body.requestId)
    except IntegrityError as error:
        if getattr(error.orig,"sqlstate",None)=="23505": raise HTTPException(409,"This maintenance request or open room issue is already recorded") from error
        raise


@app.post("/api/maintenance/{issue_id}/resolve")
def resolve_maintenance(issue_id:UUID,body:ResolveMaintenance,request:Request):
    try:
        with engine.begin() as connection:
            room_id=connection.execute(text("SELECT room_id FROM maintenance_issues WHERE id=:id"),{"id":issue_id}).scalar_one_or_none()
            if room_id is None: raise HTTPException(404,"Maintenance issue not found")
            connection.execute(text("SELECT id FROM rooms WHERE id=:id FOR UPDATE"),{"id":room_id})
            previous=connection.execute(text("SELECT * FROM maintenance_events WHERE id=:id"),{"id":body.requestId}).mappings().first()
            if previous:
                if previous["issue_id"]!=issue_id or previous["action"]!='resolved' or previous["notes"]!=body.notes:
                    raise HTTPException(409,"This request was already used with different details")
                return maintenance_response(connection,issue_id)
            issue=connection.execute(text("SELECT * FROM maintenance_issues WHERE id=:id FOR UPDATE"),{"id":issue_id}).mappings().one()
            if issue["resolved_at"] is not None: raise HTTPException(409,"Repairs for this issue are already completed")
            connection.execute(text("UPDATE maintenance_issues SET resolved_at=now(),resolved_by=:staff,resolution_notes=:notes WHERE id=:id"),{"id":issue_id,"staff":request.state.user["id"],"notes":body.notes})
            connection.execute(text("UPDATE rooms SET maintenance_status='available',cleaning_status='needs_cleaning' WHERE id=:id"),{"id":room_id})
            connection.execute(text("INSERT INTO maintenance_events(id,issue_id,action,notes,actor_id) VALUES(:id,:issue,'resolved',:notes,:staff)"),{"id":body.requestId,"issue":issue_id,"notes":body.notes,"staff":request.state.user["id"]})
            return maintenance_response(connection,issue_id)
    except IntegrityError as error:
        if getattr(error.orig,"sqlstate",None)=="23505": raise HTTPException(409,"This repair completion request is already in use") from error
        raise


from app.inventory import register_inventory
register_inventory(app, engine)

from app.bar import register_bar, bar_receipt
register_bar(app, engine)

from app.shifts import register_shifts
register_shifts(app, engine)

from app.audit import register_audit
register_audit(app, engine)

from app.alerts import register_alerts
register_alerts(app, engine)

from app.reservation_edits import register_reservation_edits
register_reservation_edits(app, engine, booking_response, lock_stay)

from app.backups import register_backups
register_backups(app, engine, password_hasher)
