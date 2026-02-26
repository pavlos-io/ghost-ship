# Event Normalizer

`normalize_events.rb` is a standalone Ruby script that reads streaming JSONL from either Claude Code or Codex CLI on stdin and emits a unified event schema to stdout. No gems required.

```bash
# Claude Code
claude -p "prompt" --output-format stream-json | ruby normalize_events.rb

# Codex
codex exec "prompt" --json | ruby normalize_events.rb
```

---

## Unified Schema Reference

### Transport format

- One JSON object per line (JSONL / NDJSON).
- Every line is self-contained — no multi-line JSON.
- Lines arrive in strict chronological order.
- The stream may be consumed in real-time (piped from a running process) or read from a completed file.

### Common envelope

Every event has exactly these three fields, plus type-specific fields described below.

| Field | Type | Description |
|---|---|---|
| `type` | `string` | Event type identifier. One of the 12 values listed below. This is the primary discriminator — use it to switch on when parsing. |
| `ts` | `string` | ISO 8601 timestamp with millisecond precision, always UTC. Example: `"2026-02-11T20:42:47.202Z"`. Monotonically non-decreasing within a stream. |
| `source` | `string` | Which agent produced the original events. Always exactly `"claude"` or `"codex"`. Constant for the entire stream — every event in a single stream has the same source. Determined automatically from the first line. |

---

## Event Types

There are 12 event types. They fall into four categories:

| Category | Types | Purpose |
|---|---|---|
| **Session lifecycle** | `session.start`, `session.end` | Bookend the entire stream. Exactly one of each per stream. |
| **Turn lifecycle** | `turn.start`, `turn.end` | Bookend each model turn. A session contains 1+ turns. |
| **Content** | `message`, `message.delta`, `thinking`, `thinking.delta` | Text the model produces (final and streaming). |
| **Tool use** | `tool.start`, `tool.delta`, `tool.end` | Tool invocations and their results. |
| **Error** | `error` | Errors that occurred during execution. |

---

### `session.start`

Emitted once, always the first event in the stream. Signals that the agent session has been initialized.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"session.start"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `session_id` | `string` \| `null` | **yes** | Opaque session identifier. For Claude this comes from the `system` init event (e.g. `"sess_abc123"`). For Codex this is the thread ID (e.g. `"th_001"`). May be `null` if the agent didn't provide one. |
| `model` | `string` \| `null` | **yes** | Model identifier used for the session (e.g. `"claude-sonnet-4-5-20250929"`, `"o4-mini"`). May be `null` if not yet known at session start (Claude sometimes reports model on the first `message_start` instead — in that case this is `null`). |

**UI notes:** Use this to initialize the session view. Display the model name and session ID if available. If `model` is null, it will appear on the first `turn.start` — you may want to update retroactively.

---

### `turn.start`

Emitted at the beginning of each model turn. A "turn" is one request-response cycle: the model receives input, thinks, produces text and/or tool calls, then stops.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"turn.start"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `turn_index` | `integer` | no | Zero-based turn counter. First turn is `0`, increments by 1 for each subsequent turn. Use this to group all events belonging to the same turn. |
| `message_id` | `string` \| `null` | **yes** | Agent-specific message identifier (e.g. `"msg_01abcXYZ"`). Opaque string. May be `null`. |

**UI notes:** Create a new turn container/section in the UI. The `turn_index` is the primary key for grouping all subsequent events until the matching `turn.end`.

---

### `message.delta`

A streaming chunk of the model's text output. Multiple `message.delta` events arrive in sequence and should be concatenated to build up the full message text in real-time.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"message.delta"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `turn_index` | `integer` | no | Which turn this belongs to. |
| `text` | `string` | no | A fragment of text to append. May be as short as a single character or as long as a full sentence. Can be an empty string `""` (rare, safe to skip in rendering). The text is raw — it may contain markdown, code blocks, newlines, etc. |

**UI notes:** Append `text` to the current turn's message buffer and re-render. This is the event to use for typewriter-style streaming. The content may contain markdown — render it accordingly.

---

### `message`

The complete, final text output for a content block. Emitted after all `message.delta` events for that block have been sent. The `text` field contains the fully accumulated text — it is the concatenation of all preceding `message.delta` texts for that block.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"message"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `turn_index` | `integer` | no | Which turn this belongs to. |
| `text` | `string` | no | The complete text of this content block. May be empty `""` if the model produced no visible text. May contain markdown, code blocks, newlines, etc. |

**UI notes:** If you are streaming with `message.delta`, you can either ignore this event (you already have the text) or use it to finalize/replace the accumulated buffer to ensure correctness. If you are NOT streaming, this is the only event you need for message text. There may be multiple `message` events per turn (one per content block), though typically there is just one.

---

### `thinking.delta`

A streaming chunk of the model's internal reasoning. Same semantics as `message.delta` but for thinking/reasoning content that the model produces before or alongside its visible output.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"thinking.delta"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `turn_index` | `integer` | no | Which turn this belongs to. |
| `text` | `string` | no | A fragment of thinking/reasoning text to append. Same rules as `message.delta` text. |

**UI notes:** Render in a separate, collapsible "Thinking" section distinct from the main message. Typically shown in a muted/secondary style. Not all turns produce thinking — only when the model uses extended thinking / reasoning mode.

---

### `thinking`

The complete, final reasoning text for a thinking content block. Emitted after all `thinking.delta` events for that block.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"thinking"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `turn_index` | `integer` | no | Which turn this belongs to. |
| `text` | `string` | no | The complete thinking/reasoning text. |

**UI notes:** Same as `message` — use to finalize or replace the accumulated thinking buffer.

---

### `tool.start`

The model is invoking a tool. Emitted when the tool call begins, before any input streaming or results.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"tool.start"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `turn_index` | `integer` | no | Which turn this belongs to. |
| `tool_use_id` | `string` | no | Unique identifier for this specific tool invocation. Use this to correlate `tool.start` → `tool.delta` → `tool.end` events. Example: `"tu_1"`, `"cmd_1"`. May be empty string `""` if the source didn't provide one. |
| `tool` | `string` | no | Normalized lowercase tool name. See the tool name table below for all known values. Examples: `"bash"`, `"read"`, `"edit"`, `"web_search"`, `"file_change"`. Unknown tools are passed through as lowercase. |
| `input` | `object` | no | Tool input parameters. For Claude source, this is always `{}` at `tool.start` time (the full input arrives via `tool.delta` events and is available in `tool.end`). For Codex source, this contains the full input immediately. |

**UI notes:** Create a new tool invocation block inside the current turn. Display the tool name prominently. The `input` may be empty at this stage for Claude — wait for `tool.end` for the complete input. Multiple tools may be invoked within a single turn, each with its own `tool_use_id`. Tools within a turn are sequential — a new `tool.start` won't appear until the previous tool's `tool.end` has been emitted.

---

### `tool.delta`

Streaming fragment of a tool's input JSON. **Claude source only** — Codex does not emit this event.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"tool.delta"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` | no | Always `"claude"`. Codex never emits this event. |
| `turn_index` | `integer` | no | Which turn this belongs to. |
| `tool_use_id` | `string` | no | Matches the `tool_use_id` from the corresponding `tool.start`. |
| `partial_json` | `string` | no | A fragment of the JSON input being streamed. Concatenate all `partial_json` values for a given `tool_use_id` to reconstruct the complete JSON input string. The fragments are NOT valid JSON individually — only the full concatenation is parseable. |

**UI notes:** If you want to show a live preview of tool input as it streams in, accumulate `partial_json` fragments and attempt to parse. Otherwise, wait for `tool.end` which has the complete parsed input. This event does not exist for Codex streams.

---

### `tool.end`

The tool invocation is complete. Contains the full, parsed input that was sent to the tool.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"tool.end"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `turn_index` | `integer` | no | Which turn this belongs to. |
| `tool_use_id` | `string` | no | Matches the `tool_use_id` from the corresponding `tool.start`. May be empty string. |
| `tool` | `string` | no | Normalized tool name (same value as in the matching `tool.start`). |
| `input` | `object` | no | The complete, parsed tool input as a JSON object. For Claude, this is the result of parsing the concatenated `tool.delta` `partial_json` fragments. For Codex, this matches the `input` from `tool.start`. May be `{}` if parsing failed or no input was provided. |

**Input object shapes by tool name:**

| Tool | Common input fields |
|---|---|
| `bash` | `{"command": "string"}` |
| `read` | `{"file_path": "string", "offset": number?, "limit": number?}` |
| `write` | `{"file_path": "string", "content": "string"}` |
| `edit` | `{"file_path": "string", "old_string": "string", "new_string": "string"}` |
| `glob` | `{"pattern": "string", "path": "string?"}` |
| `grep` | `{"pattern": "string", "path": "string?", ...}` |
| `web_search` | `{"query": "string"}` |
| `web_fetch` | `{"url": "string", "prompt": "string"}` |
| `file_change` | Codex-specific, varies |
| `mcp` | Codex-specific, varies |
| (other) | Unknown shape, treat as opaque `object` |

**UI notes:** This is the definitive event for displaying what a tool did. Show the tool name and render the input in a readable way (e.g. show the `command` for bash, the `file_path` for read/write/edit). Every `tool.start` is guaranteed to have a matching `tool.end` (unless the stream is interrupted).

---

### `turn.end`

The model's turn is complete. Contains the stop reason and token usage statistics.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"turn.end"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `turn_index` | `integer` | no | Which turn just ended. Matches the `turn_index` from the corresponding `turn.start`. |
| `status` | `"completed"` \| `"failed"` | no | Whether the turn finished successfully. `"failed"` only occurs with Codex when a `turn.failed` event is received. Claude turns always report `"completed"`. |
| `stop_reason` | `string` \| `null` | **yes** | Why the model stopped generating. Known values: `"end_turn"` (natural stop), `"tool_use"` (stopped to invoke a tool — another turn follows), `"max_tokens"` (hit token limit). May be `null` if not reported or if the turn failed. |
| `usage` | `object` \| `null` | **yes** | Token usage statistics for this turn. May be `null` if not reported. When present, it is an object with at minimum `input_tokens` and `output_tokens` as integers. May contain additional fields depending on the source (e.g. `cache_read_input_tokens`, `cache_creation_input_tokens`). |

**Usage object shape (when not null):**

```json
{
  "input_tokens": 150,
  "output_tokens": 42
}
```

May also include:
- `cache_read_input_tokens` (integer) — tokens read from prompt cache
- `cache_creation_input_tokens` (integer) — tokens written to prompt cache

**UI notes:** Use `stop_reason` to determine if more turns are coming: `"tool_use"` means the agent will process the tool result and start another turn. `"end_turn"` means the model is done (though the agent framework may still start another turn). Display usage statistics in a summary footer for the turn. Use `status` to style failed turns differently (red border, error icon, etc.).

---

### `session.end`

Emitted once, always the last event in the stream. Signals that the agent session is fully complete and no more events will follow.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"session.end"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `status` | `"completed"` \| `"failed"` | no | Overall session outcome. Currently always `"completed"` (the normalizer emits this on clean stream end). If the stream is interrupted mid-way, this event will not appear at all — the UI should handle that case. |

**UI notes:** Use this to finalize the UI — show a "Session complete" indicator, stop any loading spinners, and compute aggregate statistics (total tokens across all turns, total duration from first to last `ts`).

---

### `error`

An error occurred during execution. May appear at any point in the stream. **Codex source only in practice** — Claude Code does not emit error events through this normalizer.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `type` | `"error"` | no | Literal string. |
| `ts` | `string` | no | ISO 8601 UTC timestamp. |
| `source` | `"claude"` \| `"codex"` | no | Agent source. |
| `message` | `string` | no | Human-readable error message. Examples: `"context window exceeded"`, `"fatal: something went wrong"`, `"turn failed"`. |

**UI notes:** Display prominently as an error banner/toast within the current turn context (if within a turn) or at the session level (if outside a turn). An `error` event often immediately follows a `turn.end` with `status: "failed"`. There can be multiple `error` events in a stream.

---

## Event Ordering and Lifecycle

### Session structure

```
session.start
  turn.start (turn_index=0)
    [thinking.delta]*        ← 0 or more, only if extended thinking is enabled
    thinking                 ← 0 or 1, completes the thinking block
    [message.delta]*         ← 0 or more streaming chunks
    message                  ← 0 or more, one per text content block
    tool.start               ← 0 or more tool invocations per turn
      [tool.delta]*          ← 0 or more, Claude only
    tool.end
    [more tool.start/tool.end pairs]
  turn.end (turn_index=0)
  [error]*                   ← 0 or more
  turn.start (turn_index=1)  ← next turn if agent continues
    ...
  turn.end (turn_index=1)
  ...
session.end
```

### Guarantees

1. **Exactly one `session.start`**, always the first event.
2. **Exactly one `session.end`**, always the last event (absent only if the stream is interrupted).
3. **Turns are sequential and non-overlapping.** A `turn.start` is always followed by a `turn.end` before the next `turn.start`. `turn_index` values are sequential: 0, 1, 2, ...
4. **Content events are scoped to a turn.** Every `message.delta`, `message`, `thinking.delta`, `thinking`, `tool.start`, `tool.delta`, `tool.end` event has a `turn_index` that matches an open turn (between `turn.start` and `turn.end`).
5. **Tool events are paired.** Every `tool.start` has a matching `tool.end` with the same `tool_use_id` (unless the stream is interrupted). There are no nested tool calls — tools within a turn are strictly sequential.
6. **Delta events precede their complete counterpart.** `message.delta` events for a block always come before the `message` event for that block. Same for `thinking.delta` → `thinking` and `tool.delta` → `tool.end`.
7. **Within a turn, content blocks are sequential.** Thinking blocks (if present) come before text blocks. Text blocks come before tool blocks. However, in multi-turn sessions, the order across turns may vary.
8. **`tool.delta` is Claude-only.** Codex streams will never contain `tool.delta` events.
9. **`error` events have no guaranteed position.** They can appear after `turn.end` (most common with Codex `turn.failed`), or standalone.
10. **Multiple `message` events per turn are possible** (one per content block), but uncommon. Typically there is one text block per turn.

### Multi-turn sessions

An agent session often has multiple turns. This happens when:
- The model invokes a tool (`stop_reason: "tool_use"`) — the agent framework executes the tool and sends the result back, causing a new turn.
- The agent framework decides to continue for other reasons.

A typical multi-turn flow:

```
session.start
  turn 0: thinking → message → tool.start(bash) → tool.end → turn.end(stop_reason: "tool_use")
  turn 1: message → tool.start(edit) → tool.end → turn.end(stop_reason: "tool_use")
  turn 2: message → turn.end(stop_reason: "end_turn")
session.end
```

---

## Tool Name Reference

All tool names in `tool.start` and `tool.end` are normalized to lowercase. The full mapping:

| Unified name | Description | Source(s) |
|---|---|---|
| `bash` | Shell command execution | Claude (`Bash`), Codex (`command_execution`) |
| `read` | Read a file's contents | Claude only (`Read`) |
| `write` | Create/overwrite a file | Claude only (`Write`) |
| `edit` | String-replace edit a file | Claude only (`Edit`) |
| `glob` | Find files by pattern | Claude only (`Glob`) |
| `grep` | Search file contents by regex | Claude only (`Grep`) |
| `web_search` | Web search | Claude (`WebSearch`), Codex (`web_search`) |
| `web_fetch` | Fetch and summarize a URL | Claude only (`WebFetch`) |
| `file_change` | File modification | Codex only (`file_change`) |
| `mcp` | MCP tool call | Codex only (`mcp_tool_call`) |
| `todo_list` | Task/todo list | Codex only (`todo_list`) |
| *(anything else)* | Lowercased passthrough of original name | Either |

**UI notes for tool rendering:**

- `bash`: Show `input.command` in a code block with shell syntax highlighting. This is the most common tool.
- `read`: Show `input.file_path`. Optionally show line range if `input.offset` / `input.limit` are present.
- `write`: Show `input.file_path` and `input.content` as a code block (infer language from file extension).
- `edit`: Show `input.file_path`, with a diff-style view of `input.old_string` → `input.new_string`.
- `glob`: Show `input.pattern` (and `input.path` if present).
- `grep`: Show `input.pattern` (and `input.path` if present).
- `web_search`: Show `input.query`.
- `web_fetch`: Show `input.url`.
- `file_change`, `mcp`, `todo_list`: Codex-specific, render `input` as formatted JSON.
- Unknown tools: Render the tool name and `input` as formatted JSON.

---

## Building a UI: Recommended State Model

To render a complete session from this event stream, maintain this state:

```
Session {
  source: "claude" | "codex"
  session_id: string | null
  model: string | null
  status: "running" | "completed" | "failed"
  turns: Turn[]
  errors: Error[]           // session-level errors (outside any turn)
  started_at: string        // ts from session.start
  ended_at: string | null   // ts from session.end
}

Turn {
  turn_index: int
  message_id: string | null
  status: "running" | "completed" | "failed"
  thinking_text: string     // accumulated from thinking.delta / thinking events
  message_text: string      // accumulated from message.delta / message events
  tools: ToolUse[]
  stop_reason: string | null
  usage: object | null
  started_at: string        // ts from turn.start
  ended_at: string | null   // ts from turn.end
}

ToolUse {
  tool_use_id: string
  tool: string              // normalized name
  input: object             // from tool.end (or tool.start for Codex)
  partial_json: string      // accumulated from tool.delta (Claude only)
  status: "running" | "completed"
  started_at: string        // ts from tool.start
  ended_at: string | null   // ts from tool.end
}

Error {
  message: string
  ts: string
}
```

### Processing each event type

| Event | State mutation |
|---|---|
| `session.start` | Initialize `Session`. Set `source`, `session_id`, `model`, `started_at`. Set `status = "running"`. |
| `turn.start` | Push new `Turn` to `session.turns`. Set `turn_index`, `message_id`, `started_at`, `status = "running"`. |
| `message.delta` | Append `text` to `turns[turn_index].message_text`. |
| `message` | Set (or replace) `turns[turn_index].message_text` with `text`. |
| `thinking.delta` | Append `text` to `turns[turn_index].thinking_text`. |
| `thinking` | Set (or replace) `turns[turn_index].thinking_text` with `text`. |
| `tool.start` | Push new `ToolUse` to `turns[turn_index].tools`. Set `tool_use_id`, `tool`, `input`, `started_at`, `status = "running"`. |
| `tool.delta` | Find `ToolUse` by `tool_use_id`. Append `partial_json`. |
| `tool.end` | Find `ToolUse` by `tool_use_id`. Set `input` (complete), `ended_at`, `status = "completed"`. |
| `turn.end` | Set `turns[turn_index].status`, `stop_reason`, `usage`, `ended_at`. |
| `error` | If inside a turn (`turns.last.status == "running"`), attach to that turn. Otherwise push to `session.errors`. |
| `session.end` | Set `session.status` from `status` field. Set `ended_at`. |

### Handling interrupted streams

If the stream ends without `session.end`:
- Mark any `status: "running"` turns as `"interrupted"`.
- Mark the session as `"interrupted"`.
- Display a warning in the UI.

---

## Examples

### Claude Code

**Input** (stream-json from `claude -p "..." --output-format stream-json`):

```jsonl
{"type":"system","subtype":"init","session_id":"sess_abc123"}
{"type":"message_start","message":{"id":"msg_1","model":"claude-sonnet-4-5-20250929","role":"assistant"}}
{"type":"content_block_start","index":0,"content_block":{"type":"text"}}
{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}
{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world!"}}
{"type":"content_block_stop","index":0}
{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu_1","name":"Bash"}}
{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\"command\":"}}
{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\"ls\"}"}}
{"type":"content_block_stop","index":1}
{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":10,"output_tokens":20}}
{"type":"message_stop"}
```

**Output:**

```jsonl
{"type":"session.start","source":"claude","session_id":"sess_abc123","model":null,"ts":"2026-02-11T20:42:47.202Z"}
{"type":"turn.start","source":"claude","turn_index":0,"message_id":"msg_1","ts":"2026-02-11T20:42:47.202Z"}
{"type":"message.delta","source":"claude","turn_index":0,"text":"Hello","ts":"2026-02-11T20:42:47.202Z"}
{"type":"message.delta","source":"claude","turn_index":0,"text":" world!","ts":"2026-02-11T20:42:47.202Z"}
{"type":"message","source":"claude","turn_index":0,"text":"Hello world!","ts":"2026-02-11T20:42:47.202Z"}
{"type":"tool.start","source":"claude","turn_index":0,"tool_use_id":"tu_1","tool":"bash","input":{},"ts":"2026-02-11T20:42:47.202Z"}
{"type":"tool.delta","source":"claude","turn_index":0,"tool_use_id":"tu_1","partial_json":"{\"command\":","ts":"2026-02-11T20:42:47.202Z"}
{"type":"tool.delta","source":"claude","turn_index":0,"tool_use_id":"tu_1","partial_json":"\"ls\"}","ts":"2026-02-11T20:42:47.202Z"}
{"type":"tool.end","source":"claude","turn_index":0,"tool_use_id":"tu_1","tool":"bash","input":{"command":"ls"},"ts":"2026-02-11T20:42:47.202Z"}
{"type":"turn.end","source":"claude","turn_index":0,"status":"completed","stop_reason":"end_turn","usage":{"input_tokens":10,"output_tokens":20},"ts":"2026-02-11T20:42:47.202Z"}
{"type":"session.end","source":"claude","status":"completed","ts":"2026-02-11T20:42:47.202Z"}
```

### Claude Code with thinking

**Input:**

```jsonl
{"type":"system","subtype":"init","session_id":"sess_abc123"}
{"type":"message_start","message":{"id":"msg_1","model":"claude-sonnet-4-5-20250929"}}
{"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}
{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"Let me think..."}}
{"type":"content_block_stop","index":0}
{"type":"content_block_start","index":1,"content_block":{"type":"text"}}
{"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Hi!"}}
{"type":"content_block_stop","index":1}
{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":10,"output_tokens":20}}
{"type":"message_stop"}
```

**Output:**

```jsonl
{"type":"session.start","source":"claude","session_id":"sess_abc123","model":"claude-sonnet-4-5-20250929","ts":"..."}
{"type":"turn.start","source":"claude","turn_index":0,"message_id":"msg_1","ts":"..."}
{"type":"thinking.delta","source":"claude","turn_index":0,"text":"Let me think...","ts":"..."}
{"type":"thinking","source":"claude","turn_index":0,"text":"Let me think...","ts":"..."}
{"type":"message.delta","source":"claude","turn_index":0,"text":"Hi!","ts":"..."}
{"type":"message","source":"claude","turn_index":0,"text":"Hi!","ts":"..."}
{"type":"turn.end","source":"claude","turn_index":0,"status":"completed","stop_reason":"end_turn","usage":{"input_tokens":10,"output_tokens":20},"ts":"..."}
{"type":"session.end","source":"claude","status":"completed","ts":"..."}
```

### Codex

**Input** (from `codex exec "..." --json`):

```jsonl
{"type":"thread.started","thread_id":"th_001","model":"o4-mini"}
{"type":"turn.started","message_id":"msg_01"}
{"type":"agent_message.content.delta","delta":"Hello "}
{"type":"agent_message.content.delta","delta":"from Codex!"}
{"type":"item.completed","item":{"type":"agent_message","content":[{"text":"Hello from Codex!"}]}}
{"type":"item.started","item_type":"command_execution","item_id":"cmd_1","item":{"type":"command_execution","id":"cmd_1","input":{"command":"ls -la"}}}
{"type":"item.completed","item":{"type":"command_execution","id":"cmd_1","input":{"command":"ls -la"}}}
{"type":"reasoning.content.delta","delta":"I should think about this..."}
{"type":"item.completed","item":{"type":"reasoning","content":[{"text":"Deep thought here"}]}}
{"type":"turn.completed","stop_reason":"end_turn","usage":{"input_tokens":5,"output_tokens":15}}
```

**Output:**

```jsonl
{"type":"session.start","source":"codex","session_id":"th_001","model":"o4-mini","ts":"2026-02-11T20:42:57.283Z"}
{"type":"turn.start","source":"codex","turn_index":0,"message_id":"msg_01","ts":"2026-02-11T20:42:57.283Z"}
{"type":"message.delta","source":"codex","turn_index":0,"text":"Hello ","ts":"2026-02-11T20:42:57.283Z"}
{"type":"message.delta","source":"codex","turn_index":0,"text":"from Codex!","ts":"2026-02-11T20:42:57.283Z"}
{"type":"message","source":"codex","turn_index":0,"text":"Hello from Codex!","ts":"2026-02-11T20:42:57.283Z"}
{"type":"tool.start","source":"codex","turn_index":0,"tool_use_id":"cmd_1","tool":"bash","input":{"command":"ls -la"},"ts":"2026-02-11T20:42:57.283Z"}
{"type":"tool.end","source":"codex","turn_index":0,"tool_use_id":"cmd_1","tool":"bash","input":{"command":"ls -la"},"ts":"2026-02-11T20:42:57.283Z"}
{"type":"thinking.delta","source":"codex","turn_index":0,"text":"I should think about this...","ts":"2026-02-11T20:42:57.283Z"}
{"type":"thinking","source":"codex","turn_index":0,"text":"Deep thought here","ts":"2026-02-11T20:42:57.283Z"}
{"type":"turn.end","source":"codex","turn_index":0,"status":"completed","stop_reason":"end_turn","usage":{"input_tokens":5,"output_tokens":15},"ts":"2026-02-11T20:42:57.283Z"}
{"type":"session.end","source":"codex","status":"completed","ts":"2026-02-11T20:42:57.283Z"}
```

### Codex error/failure

**Input:**

```jsonl
{"type":"thread.started","thread_id":"th_002","model":"o4-mini"}
{"type":"turn.started","message_id":"msg_02"}
{"type":"turn.failed","error":"context window exceeded"}
{"type":"error","message":"fatal: something went wrong"}
```

**Output:**

```jsonl
{"type":"session.start","source":"codex","session_id":"th_002","model":"o4-mini","ts":"2026-02-11T20:43:12.887Z"}
{"type":"turn.start","source":"codex","turn_index":0,"message_id":"msg_02","ts":"2026-02-11T20:43:12.887Z"}
{"type":"turn.end","source":"codex","turn_index":0,"status":"failed","stop_reason":null,"usage":null,"ts":"2026-02-11T20:43:12.887Z"}
{"type":"error","source":"codex","message":"context window exceeded","ts":"2026-02-11T20:43:12.887Z"}
{"type":"error","source":"codex","message":"fatal: something went wrong","ts":"2026-02-11T20:43:12.887Z"}
{"type":"session.end","source":"codex","status":"completed","ts":"2026-02-11T20:43:12.887Z"}
```

## Validating output

```bash
ruby normalize_events.rb < input.jsonl | ruby -rjson -e 'STDIN.each_line { |l| JSON.parse(l) }; puts "All lines valid JSON"'
```
