# TODO: Slack HITL for "unclear" queries (prototype)

Goal: when `classify` returns `unclear`, post the query to a Slack channel (workspace `test-bsw1641`),
wait up to 30s for a human reply in the thread, return it to the user. On timeout, reply:
"Sorry, we are unable to reply to you at this moment."

## 1. Slack setup
- [x] Create a Slack app (`slack create` or api.slack.com) in `test-bsw1641`; bot scopes: `chat:write`, `channels:history` (add `groups:history` if the channel is private)
- [x] Install to workspace, copy the bot token
- [x] Create channel (e.g. `#support-escalations`), invite the bot, note the channel ID
- [x] Add to `.env` and `.env.example`: `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`
- [x] Add `slack_sdk` to deps: `uv add slack_sdk`

## 2. Code: `src/support_agent/slack_hitl.py` (new, ~25 lines)
- [x] `ask_human(query: str, timeout: int = 30) -> str | None`
  - `WebClient.chat_postMessage(channel, text=f"Unclear query: {query}\nReply in this thread.")` -> keep `ts`
  - Poll `conversations_replies(channel, ts)` every 10s (`POLL_INTERVAL = 10`) until `timeout` (about 3 polls)
  - Return the first reply that is not from the bot (skip the parent message, `messages[1:]`), else `None`

## 3. Code: `graph.py`
- [x] Replace `clarify` node body: call `ask_human(get_query(state))`
  - Got a reply -> `response` = human text
  - `None` -> `response` = "Sorry, we are unable to reply to you at this moment."
- [x] Keep the same edges (`unclear` -> END) and append the response to `messages` like the other nodes

## 4. Test
- [x] `uv run langgraph dev`, send an unclear query (e.g. "help")
- [x] Reply in the Slack thread within 30s -> the user gets the human reply
- [x] Don't reply -> the user gets the unavailable message after 30s
- [x] Update the eval dataset only if the unclear expected output changes (`routing_correct` should be unaffected, but `response_quality` may now judge the timeout message)

## Notes / known prototype limits
- Public Slack Web API only (outbound HTTPS, no websocket/Socket Mode/Events URL), so it works from LangSmith cloud
- Polling every 10s blocks the node for up to 30s; a reply may take up to 10s to be noticed
- Slack `conversations.replies` rate limits may throttle this; if so, adjust `POLL_INTERVAL`/timeout or move to Events + `interrupt()`
- No auth on who can reply, no concurrency handling beyond thread `ts`
- The deployed cloud agent needs the new env vars set too
- Later: use LangGraph `interrupt()` plus a Slack webhook for async replies
