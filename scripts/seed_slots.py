"""Create exam tables (if missing) and reset slots + a known test booking. Idempotent."""
import os
import subprocess
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlparse

from support_agent.db import SCHEMA, connect


def assert_test_branch() -> None:
    """Refuse to run unless DATABASE_URL points at the Neon `test` branch endpoint."""
    url = subprocess.run(["neon", "connection-string", "test", "--project-id", "bitter-art-19428841"],
                         capture_output=True, text=True, check=True).stdout.strip()
    ep = urlparse(url).hostname.split(".")[0]
    if ep not in (urlparse(os.environ["DATABASE_URL"]).hostname or ""):
        raise SystemExit("DATABASE_URL is not the Neon test branch; refusing to seed.")


assert_test_branch()

today = datetime.now(timezone.utc).date()


def at(days: int, hour: int) -> datetime:
    return datetime.combine(today + timedelta(days=days), time(hour), timezone.utc)


# (exam_type, venue, when, capacity, booked)
SLOTS = [
    ("speaking", "London Centre", at(3, 10), 3, 0),
    ("speaking", "Online", at(5, 14), 5, 0),
    ("listening", "London Centre", at(4, 9), 3, 0),
    ("listening", "Online", at(6, 11), 5, 0),
    ("writing", "London Centre", at(4, 13), 1, 0),
    ("writing", "Online", at(7, 10), 5, 0),
    ("writing", "London Centre", at(2, 9), 1, 1),  # full
    ("speaking", "London Centre", at(-1, 10), 3, 0),  # past
    ("listening", "Online", at(8, 15), 2, 0),
]
# extra normal slots: 6 per exam type across both venues, days +2..+14
for i, e in enumerate(("speaking", "listening", "writing")):
    for j in range(6):
        SLOTS.append((e, ("London Centre", "Online")[j % 2], at(2 + i + 2 * j, (9, 14)[j % 2]), 5 + (i + j) % 6, 0))

with connect() as c:
    c.execute(SCHEMA)
    c.execute("TRUNCATE bookings, exam_slots RESTART IDENTITY")
    for s in SLOTS:
        c.execute("INSERT INTO exam_slots (exam_type, venue, exam_time, capacity, booked) VALUES (%s,%s,%s,%s,%s)", s)
    c.execute("UPDATE exam_slots SET booked = 1 WHERE slot_id = 1")
    c.execute(
        "INSERT INTO bookings (booking_id, name, email, exam_type, slot_id, venue, exam_time) "
        "SELECT 'EX-TEST01', 'Test User', 'test@example.com', exam_type, slot_id, venue, exam_time "
        "FROM exam_slots WHERE slot_id = 1"
    )
    for r in c.execute("SELECT slot_id, exam_type, venue, exam_time, booked, capacity FROM exam_slots ORDER BY 1"):
        print(r)
