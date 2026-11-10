import asyncio
import os

import streamlit as st
from dotenv import load_dotenv
from langgraph_sdk import get_client

load_dotenv()

CLOUD_URL = "https://a-customer-staging-147aeebd-586a531c30f454ef83d2a652a004e2b0.apac.langgraph.app"

st.set_page_config(page_title="Customer Support", page_icon="💬")


def run(coro):
    return asyncio.run(coro)


def text_of(msg) -> str:
    c = msg.get("content", "")
    if isinstance(c, list):
        return "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c


URL = CLOUD_URL
url = URL
try:
    api_key = st.secrets.get("LANGSMITH_API_KEY", "")
except Exception:
    api_key = ""
api_key = api_key or os.getenv("LANGSMITH_API_KEY", "")
if not api_key:
    st.warning("LANGSMITH_API_KEY is not set. Add it in Streamlit Cloud → Settings → Secrets.")
assistant = "support_agent"
UI_META = {"source": "streamlit"}  # evals/other runs lack this tag, so they stay hidden


def client():
    return get_client(url=url, api_key=api_key or None)


def list_threads():
    return run(client().threads.search(metadata=UI_META, limit=30, sort_by="updated_at", sort_order="desc"))


def load_messages(thread_id):
    state = run(client().threads.get_state(thread_id))
    return state["values"].get("messages", []) if state.get("values") else []


# reset state if backend changed
if st.session_state.get("backend") != (url, assistant):
    st.session_state.backend = (url, assistant)
    st.session_state.thread_id = None
    st.session_state.messages = []
    st.session_state.mode = None

# ---------- sidebar threads ----------
with st.sidebar:
    st.header("Conversations")
    if st.button("➕ New chat", use_container_width=True):
        st.session_state.thread_id = None
        st.session_state.messages = []
        st.session_state.mode = None
        st.rerun()
    try:
        threads = list_threads()
    except Exception as e:
        threads = []
        st.error(f"Can't reach backend: {e}")
    for t in threads:
        vals = t.get("values") or {}
        msgs = vals.get("messages") if isinstance(vals, dict) else None
        first = next((text_of(m) for m in (msgs or []) if m.get("type") == "human"), "")
        label = (first[:40] + "…" if len(first) > 40 else first) or t["thread_id"][:8]
        active = t["thread_id"] == st.session_state.thread_id
        if st.button(label, key=t["thread_id"], use_container_width=True, type="primary" if active else "secondary"):
            st.session_state.thread_id = t["thread_id"]
            st.session_state.mode = "questions"
            st.session_state.messages = [
                {"role": "user" if m["type"] == "human" else "assistant", "content": text_of(m)}
                for m in load_messages(t["thread_id"])
                if m["type"] in ("human", "ai")
            ]
            st.rerun()

# ---------- main ----------
st.title("💬 Customer Support")
mode = st.session_state.get("mode")


def booking_chat():
    """Exam booking agent, run in-process (needs DATABASE_URL + OPENAI_API_KEY)."""
    import sys
    import uuid
    from pathlib import Path

    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
    from support_agent import booking, db

    @st.cache_resource
    def get_graph():
        return create_agent("openai:gpt-4.1-mini", [booking.find_slot, booking.confirm_booking, booking.get_booking],
                            system_prompt=booking.PROMPT, checkpointer=InMemorySaver())

    if "tid" not in st.session_state:
        st.session_state.tid, st.session_state.log, st.session_state.seen = str(uuid.uuid4()), [], 0
    graph, cfg, log = get_graph(), {"configurable": {"thread_id": st.session_state.tid}}, st.session_state.log

    def step(inp) -> None:
        for m in graph.invoke(inp, cfg)["messages"][st.session_state.seen:]:
            if isinstance(m, AIMessage):
                calls = [f"{c['name']}({c['args']})" for c in m.tool_calls]
                if calls or m.content:
                    log.append(("assistant", m.content, calls))
            elif isinstance(m, ToolMessage):
                log.append(("tool", m.content, []))
        st.session_state.seen = len(graph.get_state(cfg).values["messages"])

    for role, text, calls in log:
        if role == "tool":
            with st.expander("tool result"):
                st.code(text)
        else:
            with st.chat_message(role):
                for c in calls:
                    with st.expander(f"tool call: {c.split('(')[0]}"):
                        st.code(c)
                if text:
                    st.write(text)

    pending = [i for t in graph.get_state(cfg).tasks for i in t.interrupts]
    if pending:
        req = pending[0].value[0]["action_request"]["args"]
        slot = db.slot_info(req["slot_id"])
        st.info(f"Confirm booking for **{req['name']}** ({req['email']}): {req['exam_type']} at "
                f"**{slot['venue']}**, {slot['exam_time']}")
        a, b = st.columns(2)
        for col, label, val in ((a, "Confirm booking", "ok"), (b, "Decline", "decline")):
            if col.button(label, key=label):
                step(Command(resume=val))
                st.rerun()
    elif msg := st.chat_input("Type a message"):
        log.append(("user", msg, []))
        step({"messages": [HumanMessage(msg)]})
        st.rerun()


if mode is None:
    st.markdown("What would you like to do?")
    a, b = st.columns(2)
    if a.button("📅 Book an exam", use_container_width=True):
        for k in ("tid", "log", "seen"):
            st.session_state.pop(k, None)
        st.session_state.mode = "booking"
        st.rerun()
    if b.button("❓ Ask a question", use_container_width=True):
        st.session_state.mode = "questions"
        st.rerun()
elif mode == "booking":
    booking_chat()
else:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if prompt := st.chat_input("How can we help?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        async def ask(status):
            c = client()
            if not st.session_state.thread_id:
                th = await c.threads.create(metadata=UI_META)
                st.session_state.thread_id = th["thread_id"]
            reply = ""
            async for ev in c.runs.stream(
                st.session_state.thread_id,
                assistant,
                input={"messages": [{"role": "user", "content": prompt}]},
                stream_mode="updates",
            ):
                if ev.event != "updates" or not isinstance(ev.data, dict):
                    continue
                for node, upd in ev.data.items():
                    upd = upd or {}
                    if node == "classify":
                        if upd.get("category") == "unclear":
                            status.update(label="Unclear query: asking a human agent on Slack (up to ~30s)…")
                        else:
                            status.update(label=f"Routed to {upd.get('category')}, drafting reply…")
                    for m in upd.get("messages") or []:
                        if m.get("type") == "ai":
                            reply = text_of(m)
            return reply or "⚠️ No reply received."

        with st.chat_message("assistant"):
            with st.status("Thinking…", expanded=False) as status:
                try:
                    reply = run(ask(status))
                    status.update(label="Done", state="complete")
                except Exception as e:
                    reply = f"⚠️ Error: {e}"
                    status.update(label="Error", state="error")
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()
