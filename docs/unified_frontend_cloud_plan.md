# Unified Frontend + Cloud Deployment: Plan (prototype, no code yet)

Read `AGENTS.md` first. **Do not change backend logic** (`graph.py`, `booking.py`, `db.py`, `retriever.py`, `slack_hitl.py`).

## Goal
- One Streamlit app (`frontend/app.py`) with one chat window. The user first picks a path: **📅 Book an exam** or **❓ Ask a question**.
- Both paths call the **LangSmith cloud deployment** through `langgraph_sdk`: graph `exam_booking` or `support_agent`.
- Frontend on **Streamlit Cloud**, backend on **LangSmith Cloud**. Nothing runs locally in production.

## Decisions
- **One deployment, two graphs.** `langgraph.json` already registers both `support_agent` and `exam_booking`, so no code change is needed to host `booking.py`.
- **Path is locked per thread.** To switch, click "New chat" and pick again. A thread is created on one graph and stays on it.
- **Cloud URL** is the existing `CLOUD_URL` / `st.secrets` value. It is the same for both graphs; only the assistant id differs.
- **Sidebar** = "➕ New chat" button + thread history (same as today). No slots table. No DB access from the frontend.
- **Thread history tagging.** New threads are created with `metadata={"source": "streamlit", "graph": "<assistant_id>"}`. The sidebar shows 📅 or ❓ before the label. Threads with no `graph` tag default to `support_agent`. Clicking a thread sets `assistant` from its tag.
- **Tool calls are shown** in expanders for booking threads (testing phase).
- **Keep** `src/support_agent/booking.py` and `frontend/booking_app.py` as they are, for local testing. Do not delete them yet.

## Frontend changes (`frontend/app.py` only)
1. **Session state:** add `assistant` (None until chosen). `thread_id`, `messages` stay as they are.
2. **Empty state** (`assistant is None` and no messages): show a "How can we help?" prompt with two buttons. Clicking one sets `st.session_state.assistant` and reruns. The chat input is hidden until a path is chosen.
3. **Create thread** on the first message with the tagged metadata above. `runs.stream` uses `st.session_state.assistant` instead of the hardcoded `"support_agent"`.
4. **`support_agent` path:** unchanged (same status updates for `classify`).
5. **`exam_booking` path:**
   - Use `stream_mode="updates"`. It is a `create_agent` graph, so the nodes are `model` and `tools`.
   - AI messages with `tool_calls` render as expanders (`tool call: <name>`). Tool messages render as "tool result" expanders. Text replies render normally.
   - The message list in `st.session_state.messages` becomes `{role, content, calls}` so tool calls survive a rerun and a history reload. `load_messages` must also map `tool` messages and `tool_calls`.
6. **OK gate (interrupt):**
   - After a run, call `threads.get_state(thread_id)` and check `state["tasks"][*]["interrupts"]`.
   - If one is pending, show an info box with the `action_request.args` (name, email, exam type, slot id). Show **Confirm booking** / **Decline** buttons.
   - A click resumes with `runs.stream(thread_id, "exam_booking", command={"resume": "ok" | "decline"})`.
   - Hide the chat input while an interrupt is pending.
   - Note: the local app looks up venue and time through `db.slot_info`. The cloud frontend has no DB access, so the confirm box shows only the interrupt args. If venue and time are needed, the `find_slot` tool result is already visible in the expanders above it.
7. **Sidebar:** "New chat" resets `thread_id`, `messages`, `assistant`. The thread list label gets the 📅 / ❓ prefix.
8. **`frontend/requirements.txt`:** unchanged (`streamlit`, `langgraph-sdk`, `python-dotenv`).

## Cloud deployment (LangSmith) — manual steps
Your GitHub repo is already linked to a LangSmith deployment.
1. **Env vars on the deployment** (LangSmith → Deployment → Environment variables):
   `OPENAI_API_KEY`, `DATABASE_URL` (Neon **Test branch**), `LANGSMITH_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`. The last three are probably already set. `DATABASE_URL` and `OPENAI_API_KEY` are the new ones to confirm for booking.
2. **Dependencies:** check that `psycopg[binary]` is in `pyproject.toml`. LangSmith builds from it, and `db.py` imports `psycopg`. It's the only thing that could break the build.
3. **Seed slots once** against the Test branch: run `scripts/seed_slots.py` from your machine (one-time). The cloud graph then reads the same Test branch.
4. **Push `main` to GitHub.** The linked deployment rebuilds and picks up both graphs (check the Deployment → Graphs list for `support_agent` and `exam_booking`). Confirm the deployment URL matches `CLOUD_URL`.
5. **Streamlit Cloud:** point the app at `frontend/app.py`. Secrets: `LANGSMITH_API_KEY` (already set), plus the cloud URL if it's read from secrets. The frontend doesn't need `DATABASE_URL`.

## How it works at runtime
```
Streamlit Cloud (frontend/app.py)
   └─ langgraph_sdk ──HTTPS──> LangSmith deployment
                                 ├─ support_agent  (classify → draft/Slack HITL)
                                 └─ exam_booking   (ReAct + find_slot / confirm_booking[interrupt] / get_booking)
                                        └─ Neon Postgres (Test branch) via DATABASE_URL
```
Each Streamlit chat = one LangGraph thread. The thread state (history, pending interrupt) lives in LangSmith, so reloads and history clicks work without local state.

## Test checklist
- [ ] Fresh load shows two path buttons and no chat input.
- [ ] ❓ path: a billing question returns a KB-grounded reply; the thread shows ❓ in the sidebar.
- [ ] 📅 path: book an exam → tool-call expanders appear → Confirm/Decline box → Confirm returns a booking ID.
- [ ] Decline writes nothing (check the `bookings` table on Test).
- [ ] Look up the booking with ID + email.
- [ ] "New chat" returns to the path buttons; clicking an old thread reopens it on the right graph with history intact.
- [ ] Old threads without a `graph` tag open as `support_agent`.
- [ ] Nothing runs locally (no `langgraph dev`, no local DB access from the frontend).

## Out of scope (for now)
Slots table in the UI, deleting `booking_app.py`, auth, mid-thread path switching, streaming token-by-token.
