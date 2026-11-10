"""Exam booking ReAct agent (book / retrieve) backed by Neon Postgres."""
import re
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph.types import interrupt

from support_agent import db

PROMPT = (Path(__file__).parents[2] / "skills" / "exam_booking.md").read_text()
EXAMS = {"speaking", "listening", "writing"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOT_FOUND = "Booking not found or details don't match."


@tool
def find_slot(exam_type: str) -> str:
    """Find the earliest available slot for an exam type (speaking, listening or writing). Read-only."""
    exam_type = exam_type.strip().lower()
    if exam_type not in EXAMS:
        return "Invalid exam type. Choose speaking, listening or writing."
    return str(db.find_slot(exam_type) or "No slots available.")


@tool
def confirm_booking(name: str, email: str, exam_type: str, slot_id: int) -> str:
    """Book the slot after the user has agreed. Asks for final OK before writing anything."""
    email, exam_type, name = email.strip().lower(), exam_type.strip().lower(), name.strip()
    if not EMAIL.match(email):
        return "Invalid email address."
    if exam_type not in EXAMS or not name:
        return "Invalid name or exam type."
    args = {"name": name, "email": email, "exam_type": exam_type, "slot_id": slot_id}
    ans = interrupt([{  # Agent Chat UI human-interrupt schema: shows Accept/Ignore buttons
        "action_request": {"action": "confirm_booking", "args": args},
        "config": {"allow_ignore": True, "allow_respond": False, "allow_edit": False, "allow_accept": True},
        "description": "Confirm this exam booking?",
    }])
    ans = ans[0].get("type") if isinstance(ans, list) and ans and isinstance(ans[0], dict) else ans
    if str(ans).strip().lower() not in {"accept", "ok", "yes", "y", "confirm", "true"}:
        return "Booking declined. Nothing was booked."
    bid = db.create_booking(name, email, exam_type, slot_id)
    return f"Booked. Booking ID: {bid}" if bid else "Slot just filled. Call find_slot again."


@tool
def get_booking(booking_id: str, email: str) -> str:
    """Retrieve a booking. Requires both booking ID and email to match."""
    return str(db.get_booking(booking_id, email) or NOT_FOUND)


graph = create_agent("openai:gpt-4.1-mini", [find_slot, confirm_booking, get_booking], system_prompt=PROMPT)
