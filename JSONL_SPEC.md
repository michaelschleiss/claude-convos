# Claude Code JSONL Session File Specification

Reverse-engineered from real session files and the Claude Code v2.1.81 JS bundle (2026-03-22).
Verified by 8 parallel analysis agents against 1,698 files (244,990 entries). Not official documentation.

## File Location

```
~/.config/claude/projects/<encoded-project-path>/<session-id>.jsonl
~/.claude/projects/<encoded-project-path>/<session-id>.jsonl          (legacy)
```

Where `<encoded-project-path>` replaces all non-alphanumeric chars with `-` (e.g., `-home-user-myproject`).

### Session Discovery

Claude Code discovers sessions via **filesystem scan** (`readdirSync`), NOT from `sessions-index.json`.
The filename must be a valid UUID with `.jsonl` extension. Any UUID-named `.jsonl` file placed in a
project directory will be discovered on next `--resume` or session listing. The `sessions-index.json`
file (when present) is a performance cache, not the source of truth — Claude Code does not read it.

## Format

One JSON object per line (JSONL). Append-only log — compaction adds new entries but never deletes old ones.
No file-level checksums or integrity checks. No content validation on load beyond JSON parsing.

---

## All Entry Types

| Type | Has UUID? | Frequency | Purpose |
|------|-----------|-----------|---------|
| `progress` | Yes | ~61% | Streaming updates during tool/hook execution |
| `assistant` | Yes | ~20% | Claude's responses (thinking, text, tool_use) |
| `user` | Yes | ~14% | User messages and tool results |
| `system` | Yes | ~2% | Hook summaries, compaction, errors, turn timing |
| `file-history-snapshot` | No | ~2% | File state snapshots for undo/rewind |
| `queue-operation` | No | <1% | User input queue (type-ahead) |
| `last-prompt` | No | rare | Last user input for session restore (can appear multiple times) |
| `custom-title` | No | rare | User-set or fork-generated session title |
| `agent-name` | No | rare | Named agent session identifier |
| `tag` | No | rare | User-set session tag via `/tag` |
| `attribution-snapshot` | No | rare | Attribution tracking |
| `pr-link` | No | rare | Links session to a PR (`{prNumber, prUrl, prRepository}`) |
| `speculation-accept` | No | rare | Speculative decoding acceptance (`{timeSavedMs}`) |
| `content-replacement` | No | rare | Content replacement records |
| `worktree-state` | No | rare | Git worktree session info |
| `agent-color` | No | rare | Agent color in team sessions |
| `agent-setting` | No | rare | Agent settings |
| `mode` | No | rare | Session mode (e.g., plan mode) |

Note: the legacy `summary` type (with `leafUuid`) is fully replaced by `compact_boundary` + `isCompactSummary`.
Zero instances found in 1,698 files.

---

## Common Envelope Fields

Messages with UUIDs (`user`, `assistant`, `system`, `progress`) share:

```json
{
  "type":         "user|assistant|system|progress",
  "uuid":         "UUID4",
  "parentUuid":   "UUID4|null",
  "sessionId":    "UUID4",
  "cwd":          "/absolute/path",
  "version":      "2.1.81",
  "gitBranch":    "branch-name",
  "isSidechain":  false,
  "userType":     "external",
  "timestamp":    "ISO8601"
}
```

`isSidechain` is `true` on all entries in subagent session files. These entries also carry an `agentId` field
(short hash, e.g., `"aa26b6e"`). In main session files, `isSidechain` is always `false`.

Optional envelope fields:

| Field | When |
|-------|------|
| `slug` | Human-readable turn label, e.g. `"glimmering-hugging-nebula"` (LLM-generated, not a word list) |
| `teamName` | Present in team/agent contexts |
| `logicalParentUuid` | After compaction — points to pre-compaction parent. May reference UUIDs no longer in file. |
| `entrypoint` | `"cli"` on some user messages |
| `forkedFrom` | `{sessionId, messageUuid}` — present on every message in a forked session. `messageUuid` equals own `uuid`. |
| `agentId` | Short hash on subagent entries (68,180 occurrences) |
| `apiError` | Error string on some assistant entries (e.g., `"max_output_tokens"`) |
| `isMeta` | Boolean marking auto-generated/metadata messages |

---

## 1. User Messages

### 1a. Plain text (user typed a message)

Content is a **string**.

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": "please find the branch that changes docker containers"
  },
  "uuid": "dfcedb63-...",
  "parentUuid": "9f9a563f-...",
  "timestamp": "2026-02-24T10:10:36.754Z",
  "todos": [],
  "permissionMode": "default",
  "thinkingMetadata": { "maxThinkingTokens": 16000 }
}
```

`permissionMode` values: `"default"`, `"plan"`, `"acceptEdits"`, `"bypassPermissions"`, `"dontAsk"`.

`thinkingMetadata` (optional): `{level, disabled, triggers, maxThinkingTokens}` — configures extended thinking.

### 1b. Text block (e.g., user interruption)

Content is an **array** of text blocks.

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      { "type": "text", "text": "[Request interrupted by user for tool use]" }
    ]
  }
}
```

### 1c. Tool result (response to a tool_use)

Content is an **array** with one `tool_result` block per tool call.

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_016hAvN...",
        "content": "  dev\n  main\n  feature/PER-123\n...",
        "is_error": false
      }
    ]
  },
  "toolUseResult": { ... },
  "sourceToolAssistantUUID": "f9d525e3-...",
  "sourceToolUseID": "toolu_016hAvN..."
}
```

`tool_result.content` can be:
- **string** (95.3% of cases) — plain text output
- **array** (4.7%) — list of content blocks (`text`, `tool_reference`, or `image`)
- **null** (rare)

`tool_result.is_error` is **optional** — absent ~50% of the time (older sessions). When present: `true` on errors, `false` on success.

`tool_reference` blocks appear inside `tool_result.content` arrays (from ToolSearch):
```json
{"type": "tool_reference", "tool_name": "Glob"}
```

### 1d. Image content

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "image",
        "source": { "type": "base64", "media_type": "image/jpeg", "data": "..." }
      }
    ]
  }
}
```

### 1e. Document content

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "document",
        "source": { "type": "base64", "media_type": "application/pdf", "data": "..." }
      }
    ]
  }
}
```

### 1f. Compaction summary (context was compacted)

```json
{
  "type": "user",
  "isCompactSummary": true,
  "isVisibleInTranscriptOnly": true,
  "message": {
    "role": "user",
    "content": "This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion of the conversation.\n\n..."
  },
  "parentUuid": "86133565-..."
}
```

Always the immediate child of a `compact_boundary` system message (verified 48/48).
Always starts with the preamble "This session is being continued...".
May also have `promptId` field.

---

## 2. Assistant Messages

All assistant messages have `message.model`, `message.id`, `message.usage`, `requestId`.

**Key streaming behavior**: A single API response (same `message.id`) is split across **multiple JSONL lines**,
each typically containing one content block. Each line gets its own `uuid` but shares the same `message.id`.

Note: In rare cases (observed once with Haiku subagent), a single line may contain multiple `tool_use` blocks.

### 2a. Thinking block

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-6",
    "id": "msg_013mZp...",
    "type": "message",
    "role": "assistant",
    "content": [
      {
        "type": "thinking",
        "thinking": "The user wants to find a git branch...",
        "signature": "EusBCkYICxgC..."
      }
    ],
    "stop_reason": null,
    "usage": {
      "input_tokens": 3,
      "cache_creation_input_tokens": 4252,
      "cache_read_input_tokens": 15703,
      "cache_creation": {
        "ephemeral_5m_input_tokens": 0,
        "ephemeral_1h_input_tokens": 4252
      },
      "output_tokens": 11,
      "service_tier": "standard",
      "inference_geo": "not_available",
      "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
      "iterations": [],
      "speed": "standard"
    }
  },
  "requestId": "req_011CYS..."
}
```

The `signature` is a cryptographic integrity check on thinking content (appears to be protobuf-encoded, but
Anthropic describes it as "opaque" — not officially confirmed as protobuf). Always present on thinking blocks,
always base64. Not validated locally on session load; only verified by the API on subsequent calls.

### 2b. Tool use

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-6",
    "id": "msg_013mZp...",
    "role": "assistant",
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_016hAvN...",
        "name": "Bash",
        "input": {
          "command": "git branch -a | head -50",
          "description": "List all branches"
        },
        "caller": { "type": "direct" }
      }
    ],
    "usage": { ... }
  }
}
```

`caller` is **optional** — absent ~28% of the time (older sessions, some MCP tools). When present, the only
observed value is `{"type": "direct"}`. Per Anthropic docs, can also be `{"type": "code_execution_...", "tool_id": "..."}`.

Parallel tool calls are **split into separate JSONL lines** (one tool_use per line), all sharing the same `message.id`.

### 2c. Text response

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-6",
    "id": "msg_01CXoc...",
    "role": "assistant",
    "content": [
      { "type": "text", "text": "Here are the branches related to Docker..." }
    ],
    "usage": { ... }
  }
}
```

Assistant `message.content` is **always an array**, never a plain string (verified 47,858/47,858).

### 2d. Synthetic message (no API call)

```json
{
  "type": "assistant",
  "message": {
    "model": "<synthetic>",
    "id": "...",
    "role": "assistant",
    "content": [{ "type": "text", "text": "..." }]
  }
}
```

### Content block types in assistant messages

| Block type | Fields | Notes |
|------------|--------|-------|
| `thinking` | `thinking` (string), `signature` (base64) | Always exactly these 2 + `type` |
| `text` | `text` (string) | Always exactly this 1 + `type` |
| `tool_use` | `id`, `name`, `input` (object) | + optional `caller` |

### Usage fields (complete)

| Field | Notes |
|-------|-------|
| `input_tokens` | |
| `output_tokens` | |
| `cache_creation_input_tokens` | |
| `cache_read_input_tokens` | |
| `cache_creation` | `{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}` |
| `service_tier` | `"standard"` or null |
| `inference_geo` | `"not_available"` or `""` |
| `server_tool_use` | `{web_search_requests, web_fetch_requests}` |
| `iterations` | Array (always empty observed) or null |
| `speed` | `"standard"` (only value observed) |

---

## 3. System Messages

### 3a. compact_boundary

Marks a context compaction event. In non-forked sessions, creates a **new root** (`parentUuid: null`).
In forked sessions, `parentUuid` may be non-null (the fork re-links compact boundaries into a single chain).

```json
{
  "type": "system",
  "subtype": "compact_boundary",
  "content": "Conversation compacted",
  "parentUuid": null,
  "logicalParentUuid": "d73c2ecb-...",
  "compactMetadata": {
    "trigger": "auto",
    "preTokens": 167393,
    "preCompactDiscoveredTools": ["Bash", "Edit", "Glob", "Grep", "Read", "Write"],
    "userContext": "custom compaction instructions if any",
    "messagesSummarized": 42
  },
  "level": "info"
}
```

`compactMetadata` fields:
- `trigger`: `"auto"` or `"manual"` (only `"auto"` observed in data)
- `preTokens`: token count before compaction (range: 167K–175K for 200K context)
- `preCompactDiscoveredTools`: optional array of tool names (present in 6/48)
- `userContext`: optional custom compaction instructions
- `messagesSummarized`: optional count of summarized messages
- `preserved_segment`: optional `{head_uuid, anchor_uuid, tail_uuid}` for partial compaction (from Zod schema)

The next message is always a `user` with `isCompactSummary: true` (verified 48/48).

**Auto-compact threshold** (from binary): `effectiveWindow - 13,000` tokens.
For 200K context: ~167K. For 1M context: ~967K.

### 3b. microcompact_boundary

Lighter-weight compaction that truncates large tool outputs to 2KB preview + disk reference.
Does NOT create a new root (parentUuid is normal). Does NOT summarize the conversation.

```json
{
  "type": "system",
  "subtype": "microcompact_boundary",
  "content": "Context microcompacted",
  "microcompactMetadata": {
    "trigger": "auto",
    "preTokens": 68000,
    "tokensSaved": 28000,
    "compactedToolIds": ["toolu_01A...", "toolu_01B..."],
    "clearedAttachmentUUIDs": []
  }
}
```

`clearedAttachmentUUIDs` is always `[]` in observed data. Disable with `DISABLE_MICROCOMPACT=1`.

### 3c. turn_duration

```json
{
  "type": "system",
  "subtype": "turn_duration",
  "durationMs": 32160,
  "isMeta": false
}
```

### 3d. stop_hook_summary

```json
{
  "type": "system",
  "subtype": "stop_hook_summary",
  "hookCount": 2,
  "hookInfos": [
    { "command": "hooks/stop-hook.sh", "durationMs": 6 },
    { "command": "python3 hooks/stop.py", "durationMs": 31 }
  ],
  "hookErrors": [],
  "preventedContinuation": false,
  "stopReason": "",
  "hasOutput": true,
  "level": "suggestion",
  "toolUseID": "bf298fb6-..."
}
```

### 3e. api_error

```json
{
  "type": "system",
  "subtype": "api_error",
  "level": "error",
  "cause": { "code": "FailedToOpenSocket", "path": "...", "errno": 0 },
  "retryInMs": 602.11,
  "retryAttempt": 1,
  "maxRetries": 10
}
```

### 3f. local_command

Logged when the user runs a `!command` or `/slash` command.

### 3g. Other system subtypes (from binary)

Found in binary source but not observed in local data:
`api_retry`, `error`, `interrupt`, `init`, `initialize`, `elicitation`, `elicitation_complete`,
`hook_callback`, `hook_response`, `hook_started`, `mcp_message`, `mcp_reconnect`, `mcp_set_servers`,
`mcp_status`, `mcp_toggle`, `rewind_files`, `set_model`, `set_permission_mode`,
`set_max_thinking_tokens`, `status`, `apply_flag_settings`, `cancel_async_message`, `can_use_tool`,
`files_persisted`, `get_settings`, `local_command_output`, `memory_saved`, `agents_killed`

---

## 4. Progress Messages

Streaming updates during tool execution. **Not sent to the API.** Participate in the UUID chain.

### 4a. hook_progress

```json
{
  "type": "progress",
  "data": {
    "type": "hook_progress",
    "hookEvent": "SessionStart|PreToolUse|PostToolUse|Stop",
    "hookName": "SessionStart:startup",
    "command": "${CLAUDE_PLUGIN_ROOT}/hooks-handlers/session-start.sh"
  },
  "toolUseID": "...",
  "parentToolUseID": "..."
}
```

### 4b. bash_progress

```json
{
  "type": "progress",
  "data": {
    "type": "bash_progress",
    "output": "partial output...\n",
    "fullOutput": "full accumulated output...\n",
    "elapsedTimeSeconds": 3,
    "totalLines": 3,
    "totalBytes": 0,
    "taskId": "b786c0e"
  }
}
```

### 4c. agent_progress

```json
{
  "type": "progress",
  "data": {
    "type": "agent_progress",
    "prompt": "the prompt given to the agent",
    "agentId": "aeea32c06b1a4ee37",
    "message": { "type": "user", "message": { ... } },
    "normalizedMessages": []
  }
}
```

### 4d. Other progress subtypes

- `mcp_progress` — MCP tool execution
- `waiting_for_task` — background task polling
- `query_update` — search query updates (2,378 occurrences)
- `search_results_received` — search results streaming (2,378 occurrences)

---

## 5. File History Snapshot

Standalone (no uuid/parentUuid). Tracks file state for undo/rewind.

```json
{
  "type": "file-history-snapshot",
  "messageId": "dfcedb63-...",
  "snapshot": {
    "messageId": "dfcedb63-...",
    "trackedFileBackups": {},
    "timestamp": "2026-02-24T10:10:36.783Z"
  },
  "isSnapshotUpdate": false
}
```

`messageId` links to the associated user message's uuid.

---

## 6. Queue Operations

User input queued while Claude is working. No uuid/parentUuid.

```json
{
  "type": "queue-operation",
  "operation": "enqueue|dequeue|remove|popAll",
  "timestamp": "ISO8601",
  "sessionId": "UUID4",
  "content": "the queued message text"
}
```

---

## 7. Metadata-Only Entry Types

No uuid/parentUuid. `last-prompt` can appear multiple times per file (appended on each session resume).

```json
{"type": "last-prompt",  "lastPrompt": "text",    "sessionId": "UUID4"}
{"type": "custom-title", "customTitle": "text",    "sessionId": "UUID4"}
{"type": "agent-name",   "agentName":  "name",     "sessionId": "UUID4"}
{"type": "tag",          "tag":        "text",     "sessionId": "UUID4"}
```

---

## Message Filter

The binary's `En()` function determines which entries go into the conversation message array:

```javascript
function En(m) {
  return m.type === "user" || m.type === "assistant" ||
         m.type === "attachment" || m.type === "system" || m.type === "progress";
}
```

The `attachment` type is accepted but not observed in local data. Other types (file-history-snapshot,
queue-operation, metadata types) are parsed for metadata but NOT included in the conversation transcript.

---

## Tool Call Cycle

The JSONL sequence for one tool call:

```
Line N:   assistant  → content: [{type: "tool_use", name: "Bash", id: "toolu_X"}]
Line N+1: progress   → PreToolUse hook(s)
Line N+2: progress   → bash_progress (streaming output)
Line N+3: user       → content: [{type: "tool_result", tool_use_id: "toolu_X"}]
                       + toolUseResult: {stdout, stderr, ...}
                       + sourceToolAssistantUUID: uuid of assistant entry
Line N+4: progress   → PostToolUse hook(s)
Line N+5: assistant  → continuation (next tool_use or text response)
```

### Parallel tool calls

Split into separate JSONL lines sharing the same `message.id`:

```
assistant (msg_id=X) → [tool_use: Read file1]    uuid=A
assistant (msg_id=X) → [tool_use: Read file2]    uuid=B, parentUuid=A
assistant (msg_id=X) → [tool_use: Read file3]    uuid=C, parentUuid=B
...hooks...
user → [tool_result for file2]   (results may arrive out of order)
user → [tool_result for file1]
user → [tool_result for file3]
...hooks...
assistant (new msg_id) → [text: response]
```

---

## toolUseResult Metadata

The `toolUseResult` top-level field on user messages carries tool-specific structured metadata
**separate from** the `tool_result` content sent to the model.

### Per-tool schemas

| Tool | Key fields |
|------|------------|
| **Bash** | `stdout`, `stderr`, `interrupted`, `isImage`, `noOutputExpected`, `backgroundTaskId`, `persistedOutputPath`, `persistedOutputSize`, `returnCodeInterpretation`, `assistantAutoBackgrounded`, `backgroundedByUser` |
| **Read** | `type: "text"`, `file: {filePath, content}` |
| **Write** | `type: "create"`, `filePath`, `content`, `originalFile`, `structuredPatch` |
| **Edit** | `filePath`, `oldString`, `newString`, `replaceAll`, `originalFile`, `structuredPatch: [{oldStart, oldLines, newStart, newLines, lines}]`, `userModified` |
| **Glob** | `durationMs`, `filenames: [...]`, `numFiles`, `truncated` |
| **Grep** | `mode`, `numFiles`, `numLines` (optional), `filenames`, `content` (optional), `appliedLimit` (optional) |
| **Agent/Task** | `agentId`, `status`, `prompt`, `content`, `totalDurationMs`, `totalTokens`, `totalToolUseCount`, `usage`, `model`, `agent_type`, `name`, `team_name`, `color`, `is_splitpane`, `plan_mode_required`, `outputFile`, `isAsync`, `canReadOutputFile` |
| **WebSearch** | `query`, `durationSeconds`, `results: [{tool_use_id, content: [{title, url}]}]` |
| **WebFetch** | `url`, `code`, `codeText`, `bytes`, `durationMs`, `result` |
| **TaskCreate** | `task: {id, subject}`, `retrieval_status` (optional) |
| **TaskUpdate** | `success`, `taskId`, `updatedFields`, `statusChange` (optional), `error` (optional) |
| **TaskList** | `tasks: [...]` |
| **TaskGet** | `task: {...}` |
| **TaskOutput** | `retrieval_status`, `task: {task_id, task_type, status, output, ...}` |
| **TaskStop** | `task_id`, `task_type`, `command`, `message` |
| **LSP** | `operation`, `filePath`, `result`, `fileCount` (optional), `resultCount` (optional) |
| **ToolSearch** | `query`, `matches: [...]`, `total_deferred_tools` |
| **Skill** | `success`, `commandName`, `allowedTools` (optional) |
| **AskUserQuestion** | `questions`, `answers`, `annotations` (optional) |
| **SendMessage** | `success`, `message`, `routing` (optional), `request_id` (optional) |
| **EnterPlanMode** | `message` |
| **ExitPlanMode** | `plan`, `filePath`, `hasTaskTool`, `isAgent` |
| **TeamCreate** | `lead_agent_id`, `team_file_path`, `team_name` |
| **TeamDelete** | `success`, `message`, `team_name` |
| **TodoWrite** | `newTodos`, `oldTodos`, `verificationNudgeNeeded` |
| **CronCreate** | `durable`, `humanSchedule`, `id`, `recurring` |

Note: `Task` is the newer name for `Agent` — both tool names exist. They share the same schema.

---

## UUID Tree Structure

Messages form a **long linear chain** (~85-94% of nodes have exactly one child). Max branching factor is 2.

```
hook_progress (uuid=A, parentUuid=null)     ← session start
  └─ user_plain (uuid=B, parentUuid=A)
      └─ assistant_thinking (uuid=C, parentUuid=B)
          └─ assistant_tool_use (uuid=D, parentUuid=C)   ← same message.id as C
              └─ user_tool_result (uuid=E, parentUuid=D)
                  └─ assistant_text (uuid=F, parentUuid=E)
                      ├─ system_stop_hook (uuid=G, parentUuid=F)
                      ├─ system_turn_duration (uuid=H, parentUuid=F)
                      └─ user_plain (uuid=I, parentUuid=F)   ← next turn
```

### Branch points

Most "branches" (multiple children sharing a parentUuid) are **mechanical**, not conversational forks:
- **~84%** are `assistant → (progress + user)` — tool execution mechanics
- **~15%** are `assistant → (assistant + user)` — streaming chunks
- **~1%** are genuine conversation forks

### Message ordering

**99.5%+ chronological** by entry pair. Sub-second anomalies (queue-operation timing, async progress delivery)
are normal. Larger jumps (minutes) are rare and related to session suspends/resumes. The UUID chain
reconstruction (`xtH()`) walks `parentUuid` links, not line order, so reordering doesn't break loading.

### After Compaction

In non-forked sessions, each compaction creates a **new root** (`parentUuid: null`):

```
compact_boundary (uuid=X, parentUuid=null, logicalParentUuid=old_msg)
  └─ user (uuid=Y, parentUuid=X, isCompactSummary=true)
      └─ assistant (uuid=Z, parentUuid=Y)   ← conversation continues
```

A session with 6 compactions has 7 root nodes (1 original + 6 compact_boundary).

**In forked sessions**, compact_boundary entries are re-parented to the preceding entry, forming a single
continuous chain with 1 root instead of multiple roots. UUIDs are preserved but parentUuid on
compact_boundary entries is altered by the fork process.

### Forked Sessions

When a session is forked (`--fork-session` or `/fork`):
- The new JSONL file is a **complete copy** of a prefix of the parent
- **Every** message in the fork has `forkedFrom: {sessionId, messageUuid}`
- `forkedFrom.messageUuid` equals the message's own `uuid` (UUIDs are preserved verbatim)
- The fork process **re-links compact_boundary parentUuids** to create a single-rooted chain
- New messages (after the fork point) get fresh UUIDs without `forkedFrom`
- A `custom-title` entry records the fork lineage

### Session Continuation (distinct from forking)

When context is exhausted and a new session is created via `--continue`, the new file starts with a prefix
copy of records from the parent (with the parent's sessionId). The file's own session starts where the
sessionId changes. Both files share the same `slug`. No `forkedFrom` field is used.

---

## Resume / Session Loading (from binary)

1. Check file size. If >5MB, use fast path: scan for `"compact_boundary"` marker in 64KB chunks
2. Skip everything before the last `compact_boundary`
3. Parse post-boundary entries with `dx()` (JSON.parse per line)
4. Filter through `En()` — only `user`, `assistant`, `attachment`, `system`, `progress` enter the message Map
5. Walk `parentUuid` chain backwards from leaf via `xtH()` (with cycle detection)
6. `hH_()` post-processor splices in sibling assistant messages sharing the same `message.id`
7. Non-UUID entries (metadata, snapshots, queue-ops) are parsed separately for their specific purposes

---

## All Top-Level Keys (Complete Inventory)

Verified across 244,990 entries plus binary source:

```
agentId, agentName, apiError, cause, compactMetadata, content, customTitle,
cwd, data, durationMs, entrypoint, error, forkedFrom, gitBranch, hasOutput,
hookCount, hookErrors, hookInfos, isApiErrorMessage, isCompactSummary,
isMeta, isSidechain, isSnapshotUpdate, isVisibleInTranscriptOnly,
lastPrompt, level, logicalParentUuid, maxRetries, mcpMeta, message,
messageId, microcompactMetadata, operation, parentToolUseID, parentUuid,
permissionMode, planContent, preventedContinuation, promptId, requestId,
retryAttempt, retryInMs, sessionId, slug, snapshot, sourceToolAssistantUUID,
sourceToolUseID, stopReason, subtype, teamName, thinkingMetadata,
timestamp, todos, toolUseID, toolUseResult, type, userType, uuid, version
```

(59 keys)

---

## Editing Safety

| What | Safe? | Notes |
|------|-------|-------|
| Edit message text content | Yes | No content validation on load |
| Edit tool result content | Yes | No validation of content type or format |
| Delete whole lines | Mostly | Re-link children's parentUuid to deleted node's parent |
| Append new messages | Yes | Need valid UUID, chain parentUuid correctly |
| Delete progress lines | Mostly | Safe if no other message references it as parentUuid. Progress participates in UUID chain. |
| Delete file-history-snapshot | Yes | Only affects undo/rewind |
| Delete queue-operation | Yes | Only affects input queue replay |
| Edit thinking content | Risky | Not validated locally, but API rejects modified thinking on next call |
| Break UUID parentUuid chain | Tolerated | Chain stops at break; earlier messages become invisible but no crash |
| Change sessionId | Bad | Many lookups index by sessionId |
| Reorder lines | Mostly safe | Chain reconstruction uses parentUuid, not line order. Metadata uses `findLast`. |
| Add new .jsonl file | Works | Filesystem scan discovers any UUID-named .jsonl in project dir |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `DISABLE_AUTO_COMPACT` | Disable auto-compaction |
| `DISABLE_COMPACT` | Disable all compaction |
| `DISABLE_MICROCOMPACT` | Disable microcompaction |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | Set auto-compact threshold as % (can only lower, not raise) |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Override effective context window size |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | Override max output tokens |
| `CLAUDE_CODE_DISABLE_AUTO_MEMORY` | Disable auto memory |
