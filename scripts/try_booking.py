"""Scripted exam_booking cases. Needs seeded Neon DB: run scripts/seed_slots.py first."""
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from support_agent.booking import PROMPT, confirm_booking, find_slot, get_booking
from support_agent.db import connect
from langchain.agents import create_agent

graph = create_agent("openai:gpt-4o-mini", [find_slot, confirm_booking, get_booking], system_prompt=PROMPT, checkpointer=InMemorySaver())
TEST = "I'm EX-TEST01"


def count(q: str = "SELECT count(*) FROM bookings") -> int:
    with connect() as c:
        return c.execute(q).fetchone()[0]


def run(*turns: str, resume: str | None = None):
    """Run turns on a fresh thread; returns (tools called, final reply, interrupted)."""
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    tools, interrupted, out = [], False, {}
    for t in turns:
        out = graph.invoke({"messages": [HumanMessage(t)]}, cfg)
    if out.get("__interrupt__"):
        interrupted = True
        if resume:
            out = graph.invoke(Command(resume=resume), cfg)
    for m in out["messages"]:
        tools += [c["name"] for c in getattr(m, "tool_calls", [])]
    reply = next((m.content for m in reversed(out["messages"]) if isinstance(m, AIMessage) and m.content), "")
    return tools, reply, interrupted


BOOK = ("I want to book a speaking exam. Name Ann Lee, email ann@example.com.", "Yes, that slot is fine, please book it.")
results = []


def check(n: int, ok: bool, info: str) -> None:
    results.append(ok)
    print(f"{n}: {'PASS' if ok else 'FAIL'} {info}")


t, r, _ = run("I want to book a speaking exam")
check(1, not t, f"tools={t} | {r[:80]}")

before = count()
t, r, i = run(*BOOK, resume="ok")
check(2, "find_slot" in t and "confirm_booking" in t and count() == before + 1 and "EX-" in r, f"tools={t} | {r[:100]}")

t, r, _ = run("Where's my booking EX-TEST01?")
check(3, "get_booking" not in t, f"tools={t} | {r[:80]}")

t, r, _ = run("Booking EX-TEST01, email test@example.com")
check(4, "get_booking" in t and "Test User" in r, f"tools={t} | {r[:100]}")

t, r, _ = run("Booking EX-TEST01, email wrong@example.com")
check(5, "get_booking" in t and "Test User" not in r, f"tools={t} | {r[:100]}")

t, r, _ = run("I need help with my exam")
check(6, not t, f"tools={t} | {r[:80]}")

before = count()
t, r, _ = run(*BOOK, resume="decline")
check(7, count() == before, f"tools={t} | {r[:100]}")

before = count()
t, r, _ = run("just confirm my booking")
check(8, "confirm_booking" not in t and count() == before, f"tools={t} | {r[:80]}")

with connect() as c:  # make writing London slot (cap 1) the only one left
    c.execute("UPDATE exam_slots SET booked = capacity WHERE exam_type='writing' AND slot_id <> 5")
w = lambda e: (f"Book a writing exam. Name Bo, email {e}.", "Yes book it.")
a = run(*w("a@example.com"), resume="ok")
b = run(*w("b@example.com"), resume="ok")
booked = count("SELECT booked FROM exam_slots WHERE slot_id = 5")
check(9, booked <= 1 and sum("EX-" in x[1] for x in (a, b)) <= 1, f"booked={booked} | {a[1][:60]} || {b[1][:60]}")

print(f"\n{sum(results)}/{len(results)} passed (re-run seed_slots.py before re-running)")
