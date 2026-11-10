import os
import secrets
import string

import psycopg
from dotenv import load_dotenv

load_dotenv()


def connect(env: str = "DATABASE_URL") -> psycopg.Connection:
    """Neon Postgres via the pooled URL in `env` (short-lived connections)."""
    return psycopg.connect(os.environ[env])


def log_triage(query: str, category: str, confidence: float) -> None:
    """Append a triage result to `triage_log` (creates the table if needed)."""
    with connect() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS triage_log (id serial PRIMARY KEY, query text, "
            "category text, confidence real, created_at timestamptz DEFAULT now())"
        )
        c.execute("INSERT INTO triage_log (query, category, confidence) VALUES (%s, %s, %s)", (query, category, confidence))


SCHEMA = """
CREATE TABLE IF NOT EXISTS exam_slots (
  slot_id serial PRIMARY KEY, exam_type text NOT NULL, venue text NOT NULL,
  exam_time timestamptz NOT NULL, capacity int NOT NULL, booked int NOT NULL DEFAULT 0,
  CHECK (booked <= capacity));
CREATE TABLE IF NOT EXISTS bookings (
  booking_id text PRIMARY KEY, name text, email text, exam_type text,
  slot_id int REFERENCES exam_slots(slot_id), venue text, exam_time timestamptz,
  created_at timestamptz DEFAULT now());
"""


def find_slot(exam_type: str) -> dict | None:
    """Earliest future slot of this type with free capacity."""
    with connect() as c:
        r = c.execute(
            "SELECT slot_id, venue, exam_time FROM exam_slots WHERE exam_type = %s "
            "AND exam_time > now() AND booked < capacity ORDER BY exam_time LIMIT 1",
            (exam_type,),
        ).fetchone()
    return {"slot_id": r[0], "venue": r[1], "exam_time": r[2].isoformat()} if r else None


def slot_info(slot_id: int) -> dict:
    """Venue and time of a slot (for UI display)."""
    with connect() as c:
        r = c.execute("SELECT venue, exam_time FROM exam_slots WHERE slot_id = %s", (slot_id,)).fetchone()
    return {"venue": r[0], "exam_time": r[1].isoformat()} if r else {"venue": "?", "exam_time": "?"}


def create_booking(name: str, email: str, exam_type: str, slot_id: int) -> str | None:
    """Reserve a seat and insert the booking in one transaction on the default (Neon `test`) branch.
    Returns booking ID, or None if full."""
    with connect() as c:
        s = c.execute(
            "UPDATE exam_slots SET booked = booked + 1 WHERE slot_id = %s AND exam_type = %s "
            "AND exam_time > now() AND booked < capacity RETURNING venue, exam_time",
            (slot_id, exam_type),
        ).fetchone()
        if not s:
            return None
        while True:
            bid = "EX-" + "".join(secrets.choice(string.ascii_uppercase + "234567") for _ in range(6))
            if c.execute(
                "INSERT INTO bookings (booking_id, name, email, exam_type, slot_id, venue, exam_time) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING 1",
                (bid, name, email, exam_type, slot_id, s[0], s[1]),
            ).fetchone():
                return bid


def get_booking(booking_id: str, email: str) -> dict | None:
    """Booking only if both ID and email match."""
    with connect() as c:
        r = c.execute(
            "SELECT booking_id, name, exam_type, venue, exam_time FROM bookings "
            "WHERE booking_id = %s AND email = %s",
            (booking_id.strip().upper(), email.strip().lower()),
        ).fetchone()
    return dict(zip(("booking_id", "name", "exam_type", "venue", "exam_time"), (*r[:4], r[4].isoformat()))) if r else None
