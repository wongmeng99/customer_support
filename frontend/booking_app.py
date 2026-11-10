"""Local Streamlit UI for the exam_booking graph (in-process, MemorySaver). Run: uv run streamlit run frontend/booking_app.py"""
import sys
import uuid
from pathlib import Path

import streamlit as st
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from support_agent import booking, db  # noqa: E402

st.set_page_config(page_title="Exam booking (local)")


@st.cache_resource
def get_graph():
    return create_agent("openai:gpt-4.1-mini", [booking.find_slot, booking.confirm_booking, booking.get_booking],
                        system_prompt=booking.PROMPT, checkpointer=InMemorySaver())


def new_thread() -> None:
    st.session_state.tid, st.session_state.log = str(uuid.uuid4()), []


if "tid" not in st.session_state:
    new_thread()
graph, cfg = get_graph(), {"configurable": {"thread_id": st.session_state.tid}}
log = st.session_state.log  # list of (role, text, tool_calls)


def run(inp) -> None:
    """Stream one graph step, appending new tool calls/replies to the log."""
    for m in graph.invoke(inp, cfg)["messages"][st.session_state.get("seen", 0):]:
        if isinstance(m, AIMessage):
            calls = [f"{c['name']}({c['args']})" for c in m.tool_calls]
            if calls or m.content:
                log.append(("assistant", m.content, calls))
        elif isinstance(m, ToolMessage):
            log.append(("tool", m.content, []))
    st.session_state.seen = len(graph.get_state(cfg).values["messages"])


with st.sidebar:
    if st.button("New conversation"):
        st.session_state.seen = 0
        new_thread()
        st.rerun()
    st.subheader("Slots")
    with db.connect() as c:
        rows = c.execute("SELECT slot_id, exam_type, venue, exam_time, booked, capacity FROM exam_slots ORDER BY exam_time").fetchall()
    st.dataframe([dict(zip(("id", "type", "venue", "time", "booked", "cap"), r)) for r in rows], hide_index=True)

st.title("Exam booking")
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

state = graph.get_state(cfg)
pending = [i for t in state.tasks for i in t.interrupts]
if pending:
    req = pending[0].value[0]["action_request"]["args"]
    slot = db.slot_info(req["slot_id"])
    st.info(f"Confirm booking for **{req['name']}** ({req['email']}): {req['exam_type']} at "
            f"**{slot['venue']}**, {slot['exam_time']}")
    a, b = st.columns(2)
    for col, label, val in ((a, "Confirm booking", "ok"), (b, "Decline", "decline")):
        if col.button(label, key=label):
            run(Command(resume=val))
            st.rerun()
elif msg := st.chat_input("Type a message"):
    log.append(("user", msg, []))
    run({"messages": [HumanMessage(msg)]})
    st.rerun()
