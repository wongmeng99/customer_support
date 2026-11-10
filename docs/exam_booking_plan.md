# Exam Booking Feature: Plan (v1 prototype, no code yet)

Read `AGENTS.md` first. Do not change the existing `support_agent` graph.

## Goal (v1)
Prove two core functions on Neon Postgres, driven by a single ReAct agent:
1. **Book** an exam.
2. **Retrieve** an existing booking.
3. Check that the agent correctly decides between book / retrieve / ask-for-clarification.

A local **Streamlit UI** (`frontend/booking_app.py`) is part of v1 for manual testing; button clicks drive the booking steps. The test script is still kept for automated checks.

## Decisions
- **Single ReAct agent** (`create_react_agent` from `langgraph.prebuilt`, or `langchain.agents.create_agent` if the installed version recommends it; check first). It picks book vs retrieve from the conversation.
- **New files only**: `src/support_agent/booking.py`, `src/support_agent/db.py`, `skills/exam_booking.md`, `scripts/seed_slots.py`, `scripts/try_booking.py`, `frontend/booking_app.py` (local only; imports the graph directly, not the cloud URL). Register graph `exam_booking` in `langgraph.json`.
- **Skill** = markdown system prompt, loaded by `booking.py`. Procedural, not FAISS.
- **DB: Neon Postgres only**, via `DATABASE_URL` (`psycopg[binary]`, `sslmode=require`, parameterised queries). Use the Neon **Test branch** for all work; `DATABASE_URL` in `.env` already points to it. `seed_slots.py` must confirm it is connected to the Test branch (e.g. check `current_setting`/endpoint branch via `neonctl` or refuse to run if `NEON_BRANCH` check fails) and the `exam_slots` and `bookings` tables must live in that branch only, never in production/main. Neon CLI is already signed in, so the project/branch and connection string can be created with `neonctl`. Never print the URL.
- **Tools do all real work**; the LLM never invents IDs, venues or times.
- **OK gate**: `confirm_booking` calls `interrupt()` inside the tool so it cannot be skipped. In v1 the script or the Streamlit buttons resume with `"ok"` or `"decline"`. Anything other than `"ok"` writes nothing.
- **Lookup needs booking ID + email**, both must match. One generic error otherwise.

## Slots the LLM collects (book)
`name`, `email`, `exam_type` (`speaking | listening | writing`). Ask only for what is missing. Email format and normalisation (strip, lowercase) are checked in code in the tool.

## Flow: book
1. Collect name, email, exam type.
2. `find_slot(exam_type)`: read-only; returns the earliest future slot with free capacity (slot_id, venue, time), or none.
3. LLM states the venue/time and asks the user to confirm.
4. `confirm_booking(name, email, exam_type, slot_id)`: `interrupt()` first (no side effects before it), then on `"ok"` one transaction:
   `UPDATE exam_slots SET booked = booked + 1 WHERE slot_id = %s AND booked < capacity`; if 0 rows, return "slot just filled"; else insert the booking and return its ID.
5. Decline: nothing written; LLM asks if they want to start again.

## Flow: retrieve
1. LLM asks for booking ID and email if missing.
2. `get_booking(booking_id, email)`: returns details only if both match; otherwise the generic "not found or details don't match".
3. LLM relays the tool output only.

## DB schema
- `exam_slots(slot_id serial PK, exam_type text, venue text, exam_time timestamptz, capacity int, booked int default 0, CHECK (booked <= capacity))`
- `bookings(booking_id text PK, name text, email text, exam_type text, slot_id int FK, venue text, exam_time timestamptz, created_at timestamptz default now())`
- Booking ID: `EX-` + 6 random base32 chars (`secrets`), retry on collision.
- No pending rows are ever stored.
- `db.py`: small helpers (`find_slot`, `create_booking`, `get_booking`), plain psycopg, no ORM.

## Streamlit UI (v1, local)
- `uv run streamlit run frontend/booking_app.py`; loads `.env` (never printed), runs the `exam_booking` graph in-process with `MemorySaver` and a `thread_id` kept in `st.session_state`.
- Chat box for free text (name, email, exam type, booking lookups); tool calls shown in an expander.
- When the graph pauses at `confirm_booking`'s `interrupt()`, show the slot details (venue, time) with **Confirm booking** and **Decline** buttons. Confirm resumes with `"ok"`, Decline with `"decline"`. Nothing is written until Confirm is clicked.
- On confirm the tool writes the row to `bookings` (Test branch) and the UI shows the booking ID, so the row can be verified in the Neon console.
- Sidebar: "New conversation" button (new `thread_id`), and a read-only list of current slots/capacity for convenience.

## Seed data (larger, for easy testing)
`scripts/seed_slots.py` creates the tables if missing, clears and re-inserts slots (idempotent), with times relative to today (UTC). 2 venues, 3 exam types, ~24 slots: keep the 9 special-case rows below, plus extra normal slots so every exam type has at least 6 future slots with free capacity (capacity 5-10) across both venues and days today+2 to today+14.

| Exam type | Venue | When | Capacity | Purpose |
|---|---|---|---|---|
| speaking | London Centre | today+3d 10:00 | 3 | normal |
| speaking | Online | today+5d 14:00 | 5 | normal |
| listening | London Centre | today+4d 09:00 | 3 | normal |
| listening | Online | today+6d 11:00 | 5 | normal |
| writing | London Centre | today+4d 13:00 | 1 | tests "slot taken" |
| writing | Online | today+7d 10:00 | 5 | normal |
| writing | London Centre | today+2d 09:00 | 1 (booked=1) | full slot, must be skipped |
| speaking | London Centre | today-1d 10:00 | 3 | past slot, must be skipped |
| listening | Online | today+8d 15:00 | 2 | spare |
| each of speaking/listening/writing | London Centre + Online | extra days today+2..+14, 09:00/14:00 | 5-10 | extra normal slots (generate in a loop) |

Optionally the seed script also inserts one known booking (`EX-TEST01`, `test@example.com`, speaking, London slot) so retrieve can be tested without booking first. Keep the matching slot's `booked` count consistent.

## Config
- Add `DATABASE_URL` to `.env.example` (name only). Never read or print `.env`.
- `uv add "psycopg[binary]"`.
- Deploy-time: set `DATABASE_URL` on the cloud deployment (later, not v1).

## Test script (`scripts/try_booking.py`)
Runs scripted conversations against the graph, prints tool calls and final reply, and checks pass criteria. It uses a fresh `thread_id` per case.

| # | User input | Expected |
|---|---|---|
| 1 | "I want to book a speaking exam" | asks for name + email; no tool calls |
| 2 | name + email + type given | `find_slot` called, slot offered; then `confirm_booking` after the user agrees, resume `"ok"` → booking ID returned, 1 new row |
| 3 | "Where's my booking EX-TEST01?" (no email) | asks for email; `get_booking` not called |
| 4 | EX-TEST01 + correct email | `get_booking` returns details |
| 5 | EX-TEST01 + wrong email | generic not-found message |
| 6 | "I need help with my exam" | asks book or check; no tools |
| 7 | full booking flow, resume `"decline"` | no new row |
| 8 | "just confirm my booking" with no details | does not call `confirm_booking` |
| 9 | writing exam, book the capacity-1 slot twice (two threads) | second gets "slot just filled" or a different slot; `booked` never exceeds capacity |

Pass = correct tool (or no tool) per case, plus row-count checks against Neon (test branch).

## Build order
1. Neon: create/select project and a `test` branch with `neonctl`, set `DATABASE_URL` locally (not printed).
2. `db.py` + `seed_slots.py`; run the seed; check rows.
3. Tools tested directly, without the LLM (including the capacity race).
4. Skill markdown + `booking.py` + `langgraph.json`; try in `langgraph dev`.
5. `try_booking.py` and run the cases.
6. `frontend/booking_app.py`: test a full book + Confirm in the UI, then check the new row in the `bookings` table on the Test branch in the Neon console.

## v2 (deferred)
- Streamlit mode switch, cloud-deployed UI, 15s countdown (`expires_at` enforced in the tool).
- SQLite local fallback.
- Idempotent confirm (idempotency key), lookup attempt limits / per-email rate limit.
- "Another time" slot requests, cancel/reschedule.
- PII masking in LangSmith traces, time zone display.
- LangSmith eval dataset `exam-booking-golden` (separate from `support-routing-golden`).
- Cloud deploy with `DATABASE_URL` and smoke test.
- Model upgrade if `gpt-4o-mini` tool calling is unreliable.
