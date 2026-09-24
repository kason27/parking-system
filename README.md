# ParkFlow Kenya

A deployable web-based parking operations system for automated vehicle entry, live slot visibility, parking fee calculation, payment-gated exit, and barrier control.

## Run it

### Local development

```bash
python -m pip install -r requirements.txt
python backend/app.py
```

Open `http://127.0.0.1:5000`. The default database is SQLite (`parking.db`) and the default barrier mode is `simulated`.

### PostgreSQL with Docker

```bash
docker compose up --build
```

This starts PostgreSQL and the API together at `http://127.0.0.1:5000`. Change the database password in `docker-compose.yml` before using it outside local development.

The frontend no longer stores operational records in the browser. Every dashboard refresh, arrival, quote, payment, and barrier event uses the backend API.

### Real barrier controller

The safe default is simulation. To connect a gateway device that exposes an authenticated HTTP command endpoint, set:

```env
BARRIER_MODE=http
BARRIER_URL=https://your-gateway.example/open
BARRIER_TOKEN=replace-with-a-secret
```

The API sends `POST {"action":"open","session_id":"..."}` and only completes the parking session after the controller returns a successful HTTP status. For a relay or Raspberry Pi installation, put the GPIO/MQTT-specific code inside `BarrierController.open()` in `backend/app.py`; never expose GPIO directly to the browser.

## Modules and use cases

1. **Live availability board** - Displays all 40 ground-floor slots using clear available and occupied states. A driver/operator can see the current capacity before entry.
2. **Vehicle entry and slot assignment** - Captures the Kenyan registration plate, vehicle type, entry timestamp, and selected available slot.
3. **Parking session management** - Keeps active sessions separate from completed sessions and updates occupancy immediately after every event.
4. **Exit checkout and barrier control** - Calculates duration from entry to payment, shows the amount due, records the payment method, and releases the simulated barrier only after payment.
5. **Operations dashboard** - Shows occupancy, daily revenue, arrivals, average completed stay, recent activity, and the rate card.
6. **Dynamic persistence** - Stores vehicles, slots, sessions, payments, and barrier events in SQL through the backend API. PostgreSQL is supported for shared multi-operator deployments.

## Algorithms

### Slot availability

- Create the slot set `G-01` to `G-40`.
- Find active sessions where `exitTime` is null.
- Mark their slot IDs as occupied.
- Render occupied slots with a dark state and available slots with an interactive green state.
- On entry, assign a selected slot only if it is not in the occupied set.

### Vehicle arrival

- Validate and normalize the plate to uppercase.
- Confirm a slot is available and selected.
- Create a session with a unique ID, plate, type, slot, and current timestamp.
- Persist the session and refresh the map, counters, and arrival list.

### Fee calculation

Given total parked minutes:

```text
0-30 minutes       = Ksh 0
31-120 minutes     = Ksh 50
121-240 minutes    = Ksh 100
241-360 minutes    = Ksh 300
more than 360      = Ksh 500
```

The checkout calculates `round((exitTime - entryTime) / 60,000)` and applies the first matching tariff band.

### Payment and exit

- Identify the active session from the selected slot or arrival row.
- Calculate minutes and fee.
- Display plate, slot, entry time, duration, and amount due.
- On payment confirmation, write `exitTime`, `durationMinutes`, `fee`, and `paymentMethod`.
- Remove the session from active occupancy; the success toast represents the barrier-open command.

## Data structures and rationale

- **Array of parking sessions:** preserves an activity history and is easy to filter for active, completed, or today's records.
- **Session object:** groups the transaction's identity, vehicle, slot, timestamps, fee, and payment state into one auditable record.
- **Set-equivalent occupied slot lookup:** the UI derives occupied slots from active sessions, preventing duplicate assignments and keeping one source of truth.
- **Tariff decision table:** the ordered `calculateFee` conditions make the pricing bands explicit and easy to move into a database/configuration service.

## Production database design

The live API uses this relational model:

```sql
CREATE TABLE parking_slots (
  id INTEGER PRIMARY KEY,
  site_id INTEGER NOT NULL,
  slot_code VARCHAR(10) NOT NULL UNIQUE,
  floor VARCHAR(30) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'available'
);

CREATE TABLE vehicles (
  id BIGINT PRIMARY KEY,
  registration_no VARCHAR(12) NOT NULL UNIQUE,
  vehicle_type VARCHAR(30) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE parking_sessions (
  id BIGINT PRIMARY KEY,
  vehicle_id BIGINT NOT NULL REFERENCES vehicles(id),
  slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
  entry_time TIMESTAMP NOT NULL,
  exit_time TIMESTAMP NULL,
  duration_minutes INTEGER NULL,
  amount_due DECIMAL(10,2) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active'
);

CREATE TABLE payments (
  id BIGINT PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES parking_sessions(id),
  amount DECIMAL(10,2) NOT NULL,
  method VARCHAR(20) NOT NULL,
  reference VARCHAR(60) NULL,
  paid_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tariffs (
  id INTEGER PRIMARY KEY,
  min_minutes INTEGER NOT NULL,
  max_minutes INTEGER NULL,
  amount DECIMAL(10,2) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE
);
```

Important production constraints include a unique active-session rule per slot, a unique vehicle registration index, database transactions around payment and barrier commands, audit logs for operator actions, M-Pesa API callbacks, authentication and role permissions, and a hardware adapter for entry/exit barriers and LED signage.

## Suggested production modules

- **Driver display / signage service:** reads slot availability and publishes it to an LED board at the entrance.
- **Entry controller:** plate reader or operator form, slot assignment, ticket/QR generation.
- **Session API:** authoritative timestamps and active-session state.
- **Tariff and billing service:** configurable rates, rounding policy, receipts, and tax reporting.
- **Payments service:** M-Pesa STK Push/callbacks plus cash reconciliation.
- **Barrier controller:** opens only after a verified payment event and logs the command.
- **Reporting and administration:** occupancy trends, revenue, tariff management, user roles, and exports.
