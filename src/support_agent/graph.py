from typing import Annotated, Literal, TypedDict

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from support_agent.retriever import retrieve
from support_agent.slack_hitl import ask_human

load_dotenv()

Category = Literal["billing", "technical", "account", "unclear"]

llm = init_chat_model("openai:gpt-4o-mini", temperature=0)


class Classification(BaseModel):
    category: Category = Field(description="Primary category of the query. Use 'unclear' if none fit.")
    confidence: float = Field(ge=0, le=1)


class State(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    query: str
    category: Category
    confidence: float
    response: str


def get_query(state: State) -> str:
    # Latest human message wins; `query` persists in thread state, so it must be only a fallback.
    for m in reversed(state.get("messages", [])):
        if getattr(m, "type", None) == "human":
            if isinstance(m.content, str):
                return m.content
            return " ".join(b.get("text", "") for b in m.content if isinstance(b, dict))
    return state.get("query", "")


def classify(state: State) -> State:
    result = llm.with_structured_output(Classification).invoke(
        "Classify this customer support query as billing, technical, account, or unclear. "
        "If multiple intents, pick the primary one.\n\nQuery: " + get_query(state)
    )
    return {"query": get_query(state), "category": result.category, "confidence": result.confidence}


def route(state: State) -> str:
    return state["category"]


def make_drafter(dept: str):
    def draft(state: State) -> State:
        query = get_query(state)
        docs = retrieve(query, dept)
        if not docs:
            text = "I couldn't find this in our help docs, so I'm connecting you with a human agent who can help."
            return {"response": text, "messages": [AIMessage(text)]}
        kb = "\n\n".join(d["text"] for d in docs)
        msg = llm.invoke(
            f"You are a {dept} support agent. Draft a short, friendly reply using ONLY this "
            f"knowledge base; don't invent policies.\nKB:\n{kb}\n\nCustomer: {query}"
        )
        return {"response": msg.content, "messages": [AIMessage(msg.content)]}

    return draft


def clarify(state: State) -> State:
    query = get_query(state)
    human = ask_human(query)
    if human:
        text = llm.invoke(
            "Rewrite this human support agent's reply as a short, friendly message to the customer. "
            "Keep the meaning exactly; don't add facts or policies.\n\n"
            f"Customer: {query}\nAgent reply: {human}"
        ).content
    else:
        text = "Sorry, we are unable to reply to you at this moment."
    return {"response": text, "messages": [AIMessage(text)]}


g = StateGraph(State)
g.add_node("classify", classify)
for d in ("billing", "technical", "account"):
    g.add_node(d, make_drafter(d))
g.add_node("unclear", clarify)
g.add_edge(START, "classify")
g.add_conditional_edges("classify", route, ["billing", "technical", "account", "unclear"])
for d in ("billing", "technical", "account", "unclear"):
    g.add_edge(d, END)

graph = g.compile()
