-- PostgreSQL reference schema. The Flask application creates the same tables through SQLAlchemy.
CREATE TABLE parking_slots (
  id SERIAL PRIMARY KEY,
  site_id INTEGER NOT NULL DEFAULT 1,
  code VARCHAR(10) NOT NULL UNIQUE,
  floor VARCHAR(30) NOT NULL DEFAULT 'Ground floor',
  status VARCHAR(20) NOT NULL DEFAULT 'available'
);

CREATE TABLE vehicles (
  id SERIAL PRIMARY KEY,
  registration_no VARCHAR(12) NOT NULL UNIQUE,
  vehicle_type VARCHAR(30) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE parking_sessions (
  id UUID PRIMARY KEY,
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
  entry_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  exit_time TIMESTAMPTZ,
  duration_minutes INTEGER,
  amount_due INTEGER,
  status VARCHAR(20) NOT NULL DEFAULT 'active'
);

CREATE UNIQUE INDEX one_active_session_per_slot ON parking_sessions(slot_id) WHERE status = 'active';
CREATE UNIQUE INDEX one_active_session_per_vehicle ON parking_sessions(vehicle_id) WHERE status = 'active';

CREATE TABLE payments (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES parking_sessions(id),
  amount INTEGER NOT NULL,
  method VARCHAR(20) NOT NULL,
  reference VARCHAR(60),
  paid_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE barrier_events (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL,
  direction VARCHAR(10) NOT NULL,
  mode VARCHAR(20) NOT NULL,
  success BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
