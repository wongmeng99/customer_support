# AGENTS.md

Customer-support triage agent built on LangGraph. Classifies a query (billing / technical / account / unclear),
retrieves from a FAISS knowledge base, and drafts a reply using ONLY retrieved KB text. Python 3.12, managed with `uv`.

## Layout (read this instead of grepping)
- `src/support_agent/graph.py` – the whole graph (84 lines). Exposed as `graph`; registered in `langgraph.json`.
  - Nodes: `classify` -> conditional route -> `billing` | `technical` | `account` (made by `make_drafter(dept)`) | `unclear` (`clarify`, Slack HITL) -> END.
  - `State` keys: `messages`, `query`, `category`, `confidence`, `response`.
  - `get_query()`: latest human message wins; `state["query"]` is only a fallback (it persists in thread state).
  - LLM: `openai:gpt-4o-mini`, temperature 0.
- `src/support_agent/slack_hitl.py` – `ask_human(query, timeout=30)`: posts to Slack `SLACK_CHANNEL_ID`, polls every 10s for a non-bot reply (thread or channel message), returns text or `None`.
  `clarify` rewrites the human reply with the LLM (no new facts); on `None` returns "Sorry, we are unable to reply to you at this moment."
- `src/support_agent/retriever.py` – `retrieve(query, category, k=4)`. Loads `index/` at import time.
  Searches category + `general` first, falls back to unfiltered if top score < `MIN_SCORE` (0.30, cosine). `FETCH_K=20`.
- `scripts/build_index.py` – builds `index/kb.faiss` + `index/meta.json` from `kb/*.md`
  (one chunk per `# Heading`; category = file stem; embeddings `text-embedding-3-small`).
- `kb/{account,billing,general,technical}.md` – KB source. Filename stem = category. `general` is searched for every dept.
- `evals/create_dataset.py`, `evals/run_eval.py` – LangSmith dataset `support-routing-golden`; evaluators: `routing_correct` (exact match) and `response_quality` (LLM judge).
- `frontend/app.py` – Streamlit UI calling the deployed LangGraph cloud agent via `langgraph_sdk` (hardcoded `CLOUD_URL`; key from `st.secrets["LANGSMITH_API_KEY"]`). Has its own `frontend/requirements.txt`.
- `langgraph.json` – graph id `support_agent`, env `.env`.

## Commands
- Install: `uv sync`
- Dev server: `uv run langgraph dev`
- Rebuild index (REQUIRED after editing `kb/`): `uv run python scripts/build_index.py`
- Create eval dataset: `uv run python evals/create_dataset.py`
- Run evals: `uv run python evals/run_eval.py`
- Frontend: `uv run streamlit run frontend/app.py`
- No unit tests or linter configured.

## Conventions / gotchas
- Never read or print `.env` (contains real keys). Use `.env.example` for variable names
  (`OPENAI_API_KEY`, `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`).
- Don't invent policies in prompts: drafters must stay grounded in KB text; no docs -> human handoff message.
- Adding a category: update `Category` Literal, classifier prompt, `route` targets, the node/edge loops in `graph.py`,
  add `kb/<category>.md`, rebuild index, and update eval dataset.
- Do not open/edit: `index/*` (generated), `uv.lock`, `.langgraph_api/` (local dev state, gitignored), `.venv/`.
- Slack bot (`customer_support`) must be invited to the channel; needs `chat:write`, `channels:history`. Set the Slack env vars on the cloud deployment too.
- Importing `retriever` needs `index/` to exist and an OpenAI key (loads index + embeddings at import).
- Keep code small and terse; match existing style (type hints, short docstrings, no extra abstractions).
