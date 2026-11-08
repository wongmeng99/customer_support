import os
import time

from slack_sdk import WebClient

POLL_INTERVAL = 10


def ask_human(query: str, timeout: int = 30) -> str | None:
    """Post query to Slack, poll the thread for a human reply; None on timeout."""
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    channel = os.environ["SLACK_CHANNEL_ID"]
    ts = client.chat_postMessage(channel=channel, text=f"Unclear query: {query}\nReply in this thread.")["ts"]
    bot_id = client.auth_test()["user_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
        thread = client.conversations_replies(channel=channel, ts=ts)["messages"][1:]
        recent = client.conversations_history(channel=channel, oldest=ts)["messages"][::-1]
        for m in thread + [m for m in recent if m["ts"] != ts]:  # thread replies or plain channel messages
            if m.get("user") != bot_id and not m.get("bot_id"):
                return m["text"]
    return None
