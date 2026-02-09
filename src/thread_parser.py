import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger("app.thread_parser")


def clean_slack_message(text: str, users_map: dict[str, str]) -> str:
    """Strip Slack markup and resolve user mentions."""
    original = text
    # <@U12345> → @alice
    text = re.sub(
        r"<@(\w+)>",
        lambda m: f"@{users_map.get(m.group(1), 'unknown')}",
        text,
    )
    # <https://url|label> → label (url)
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", text)
    # <https://url> → url
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    cleaned = text.strip()
    if cleaned != original.strip():
        logger.debug(f"Cleaned message: {original[:80]!r} → {cleaned[:80]!r}")
    return cleaned


def parse_thread(
    messages: list[dict], users_map: dict[str, str]
) -> list[dict]:
    """Structure raw Slack messages into a clean list with author names."""
    parsed = []
    for msg in messages:
        user_id = msg.get("user", "")
        author = users_map.get(user_id, user_id)
        ts = float(msg.get("ts", 0))
        timestamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        cleaned = clean_slack_message(msg.get("text", ""), users_map)

        has_code = "```" in cleaned
        has_error = any(
            kw in cleaned.lower()
            for kw in ["error", "exception", "traceback", "failed"]
        )

        if has_code:
            logger.debug(f"Message from @{author} contains code block")
        if has_error:
            logger.debug(f"Message from @{author} contains error keywords")

        parsed.append(
            {
                "author": author,
                "text": cleaned,
                "ts": msg.get("ts", ""),
                "timestamp": timestamp,
                "has_code": has_code,
                "has_error": has_error,
            }
        )
    logger.debug(f"Parsed {len(parsed)} messages from thread")
    return parsed


def trim_thread(parsed: list[dict], max_chars: int = 8000) -> list[dict]:
    """Keep first + trigger + code/error messages, drop filler if over budget."""
    if not parsed:
        return parsed

    total = sum(len(m["text"]) for m in parsed)
    logger.debug(f"Thread size: {total} chars (budget: {max_chars})")

    if total <= max_chars:
        return parsed

    # Always keep: first message, last message (trigger), code/error messages
    keep_indices = {0, len(parsed) - 1}
    for i, msg in enumerate(parsed):
        if msg["has_code"] or msg["has_error"]:
            keep_indices.add(i)

    kept = [parsed[i] for i in sorted(keep_indices)]
    dropped = len(parsed) - len(kept)
    logger.info(f"Thread over budget — kept {len(kept)}, dropped {dropped} filler messages")

    # If still over budget, truncate middle messages
    while sum(len(m["text"]) for m in kept) > max_chars and len(kept) > 2:
        longest_idx = max(
            range(1, len(kept) - 1), key=lambda i: len(kept[i]["text"])
        )
        removed = kept.pop(longest_idx)
        logger.debug(f"Dropped long message from @{removed['author']} ({len(removed['text'])} chars)")

    return kept


def format_thread(parsed: list[dict]) -> str:
    """Render parsed thread as a readable string for context."""
    lines = []
    for msg in parsed:
        lines.append(f"@{msg['author']} ({msg['timestamp']}):")
        lines.append(msg["text"])
        lines.append("")
    return "\n".join(lines)
