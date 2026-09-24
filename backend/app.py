import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, static_folder=str(ROOT), static_url_path="")
CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*").split(",")}})

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + str(ROOT / "parking.db"))
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+" not in DATABASE_URL.split("://", 1)[0]:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
app.config.update(SQLALCHEMY_DATABASE_URI=DATABASE_URL, SQLALCHEMY_TRACK_MODIFICATIONS=False)
db = SQLAlchemy(app)

SITE_ID = 1
SLOT_COUNT = 40
PLATE_PATTERN = re.compile(r"^[A-Z]{2,3}\s?\d{3,4}[A-Z]?$")


class ParkingSlot(db.Model):
    __tablename__ = "parking_slots"
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, nullable=False, default=SITE_ID)
    code = db.Column(db.String(10), unique=True, nullable=False)
    floor = db.Column(db.String(30), nullable=False, default="Ground floor")
    status = db.Column(db.String(20), nullable=False, default="available")


class Vehicle(db.Model):
    __tablename__ = "vehicles"
    id = db.Column(db.Integer, primary_key=True)
    registration_no = db.Column(db.String(12), unique=True, nullable=False)
    vehicle_type = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class ParkingSession(db.Model):
    __tablename__ = "parking_sessions"
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey("parking_slots.id"), nullable=False)
    entry_time = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    exit_time = db.Column(db.DateTime(timezone=True))
    duration_minutes = db.Column(db.Integer)
    amount_due = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="active")
    vehicle = db.relationship("Vehicle")
    slot = db.relationship("ParkingSlot")


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = db.Column(db.String(36), db.ForeignKey("parking_sessions.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    method = db.Column(db.String(20), nullable=False)
    reference = db.Column(db.String(60))
    paid_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class BarrierEvent(db.Model):
    __tablename__ = "barrier_events"
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = db.Column(db.String(36), nullable=False)
    direction = db.Column(db.String(10), nullable=False)
    mode = db.Column(db.String(20), nullable=False)
    success = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def now_utc():
    return datetime.now(timezone.utc)


def as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def fee_for(minutes):
    if minutes <= 30:
        return 0
    if minutes <= 120:
        return 50
    if minutes <= 240:
        return 100
    if minutes <= 360:
        return 300
    return 500


def session_json(session):
    return {
        "id": session.id,
        "plate": session.vehicle.registration_no,
        "vehicleType": session.vehicle.vehicle_type,
        "slot": session.slot.id,
        "slotCode": session.slot.code,
        "entryTime": as_utc(session.entry_time).isoformat(),
        "exitTime": as_utc(session.exit_time).isoformat() if session.exit_time else None,
        "durationMinutes": session.duration_minutes,
        "fee": session.amount_due,
        "status": session.status,
    }


class BarrierController:
    """Hardware boundary: simulation is safe for development; HTTP controls a real gateway."""

    def __init__(self):
        self.mode = os.getenv("BARRIER_MODE", "simulated").lower()
        self.url = os.getenv("BARRIER_URL", "")
        self.token = os.getenv("BARRIER_TOKEN", "")

    def open(self, session_id):
        if self.mode == "simulated":
            return True
        if self.mode != "http" or not self.url:
            raise RuntimeError("Barrier is not configured. Set BARRIER_MODE=simulated or configure BARRIER_URL.")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = ('{"action":"open","session_id":"' + session_id + '"}').encode("utf-8")
        try:
            with urlopen(Request(self.url, data=payload, headers=headers, method="POST"), timeout=5) as response:
                return 200 <= response.status < 300
        except (HTTPError, URLError) as error:
            app.logger.error("Barrier controller failed: %s", error)
            return False


barrier = BarrierController()


def seed_slots():
    if ParkingSlot.query.count() == 0:
        db.session.bulk_save_objects([ParkingSlot(code=f"G-{number:02d}") for number in range(1, SLOT_COUNT + 1)])
        db.session.commit()


@app.get("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "database": app.config["SQLALCHEMY_DATABASE_URI"].split(":", 1)[0], "barrierMode": barrier.mode})


@app.get("/api/slots")
def slots():
    active = {session.slot_id for session in ParkingSession.query.filter_by(status="active").all()}
    return jsonify([{"id": slot.id, "code": slot.code, "floor": slot.floor, "status": "occupied" if slot.id in active else "available"} for slot in ParkingSlot.query.order_by(ParkingSlot.id).all()])


@app.get("/api/dashboard")
def dashboard():
    sessions = ParkingSession.query.order_by(ParkingSession.entry_time.desc()).all()
    today = now_utc().date()
    today_sessions = [item for item in sessions if as_utc(item.entry_time).date() == today]
    completed = [item for item in today_sessions if item.status == "completed"]
    durations = [item.duration_minutes for item in completed if item.duration_minutes is not None]
    return jsonify({
        "slots": [session_json(item) for item in sessions],
        "occupancy": ParkingSession.query.filter_by(status="active").count(),
        "capacity": SLOT_COUNT,
        "revenue": sum(item.amount_due or 0 for item in completed),
        "vehiclesToday": len(today_sessions),
        "activeVehicles": ParkingSession.query.filter_by(status="active").count(),
        "averageStayMinutes": round(sum(durations) / len(durations)) if durations else 0,
    })


@app.post("/api/sessions")
def create_session():
    data = request.get_json(silent=True) or {}
    plate = " ".join(str(data.get("plate", "")).upper().split())
    vehicle_type = str(data.get("vehicleType", "Saloon"))
    slot_id = data.get("slot")
    if not PLATE_PATTERN.match(plate):
        return jsonify({"error": "Enter a valid Kenyan registration, for example KDA 123A."}), 400
    if vehicle_type not in {"Saloon", "SUV", "Motorcycle", "Van"}:
        return jsonify({"error": "Unsupported vehicle type."}), 400
    slot = db.session.get(ParkingSlot, slot_id)
    if not slot or ParkingSession.query.filter_by(slot_id=slot_id, status="active").first():
        return jsonify({"error": "That parking slot is no longer available."}), 409
    if ParkingSession.query.join(Vehicle).filter(Vehicle.registration_no == plate, ParkingSession.status == "active").first():
        return jsonify({"error": "This vehicle already has an active parking session."}), 409
    vehicle = Vehicle.query.filter_by(registration_no=plate).first() or Vehicle(registration_no=plate, vehicle_type=vehicle_type)
    vehicle.vehicle_type = vehicle_type
    session = ParkingSession(vehicle=vehicle, slot=slot)
    slot.status = "occupied"
    db.session.add(session)
    db.session.commit()
    return jsonify(session_json(session)), 201


@app.get("/api/sessions/<session_id>/quote")
def quote(session_id):
    session = db.session.get(ParkingSession, session_id)
    if not session or session.status != "active":
        return jsonify({"error": "Active parking session not found."}), 404
    minutes = max(0, round((now_utc() - as_utc(session.entry_time)).total_seconds() / 60))
    return jsonify({"session": session_json(session), "durationMinutes": minutes, "amountDue": fee_for(minutes)})


@app.post("/api/sessions/<session_id>/checkout")
def checkout(session_id):
    data = request.get_json(silent=True) or {}
    method = data.get("paymentMethod", "M-Pesa")
    if method not in {"M-Pesa", "Cash"}:
        return jsonify({"error": "Unsupported payment method."}), 400
    session = db.session.get(ParkingSession, session_id)
    if not session or session.status != "active":
        return jsonify({"error": "Active parking session not found."}), 404
    exit_time = now_utc()
    minutes = max(0, round((exit_time - as_utc(session.entry_time)).total_seconds() / 60))
    amount = fee_for(minutes)
    if not barrier.open(session.id):
        db.session.add(BarrierEvent(session_id=session.id, direction="exit", mode=barrier.mode, success=False))
        db.session.commit()
        return jsonify({"error": "Barrier controller did not confirm an open command."}), 502
    session.exit_time = exit_time
    session.duration_minutes = minutes
    session.amount_due = amount
    session.status = "completed"
    session.slot.status = "available"
    db.session.add(Payment(session_id=session.id, amount=amount, method=method, reference=data.get("reference")))
    db.session.add(BarrierEvent(session_id=session.id, direction="exit", mode=barrier.mode, success=True))
    db.session.commit()
    return jsonify({"session": session_json(session), "amountPaid": amount, "barrier": "open"})


with app.app_context():
    db.create_all()
    seed_slots()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
