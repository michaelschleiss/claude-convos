# Claude Code JSONL Session File Specification

Reverse-engineered from real session files (2026-03-22). Not official documentation.

## File Location

```
~/.config/claude/projects/<encoded-project-path>/<session-id>.jsonl
```

Where `<encoded-project-path>` replaces all non-alphanumeric chars with `-` (e.g., `-home-user-myproject`).

A `sessions-index.json` in each project directory provides fast metadata lookup.

## Format

One JSON object per line (JSONL). No file-level checksums or integrity checks.

---

## All Entry Types

| Type | Has UUID? | Frequency | Purpose |
|------|-----------|-----------|---------|
| `progress` | Yes | ~75% | Streaming updates during tool/hook execution |
| `assistant` | Yes | ~12% | Claude's responses (thinking, text, tool_use) |
| `user` | Yes | ~8% | User messages and tool results |
| `system` | Yes | ~2% | Hook summaries, compaction, errors, turn timing |
| `file-history-snapshot` | No | ~3% | File state snapshots for undo/rewind |
| `queue-operation` | No | <1% | User input queue (type-ahead) |
| `summary` | No | rare | Legacy compaction format (see §3a for current) |
| `last-prompt` | No | rare | Last user input for session restore |
| `custom-title` | No | rare | User-set session title |
| `agent-name` | No | rare | Named agent session identifier |

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

Optional envelope fields:

| Field | When |
|-------|------|
| `slug` | Human-readable turn label, e.g. `"glimmering-hugging-nebula"` |
| `teamName` | Present in team/agent contexts |
| `logicalParentUuid` | After compaction — points to pre-compaction parent |
| `entrypoint` | `"cli"` on some user messages |
| `forkedFrom` | `{sessionId, messageUuid}` — present on every message in a forked session |

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
  "permissionMode": "default"
}
```

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

### 1d. Image content

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "image",
        "source": {
          "type": "base64",
          "media_type": "image/jpeg",
          "data": "..."
        }
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
        "source": {
          "type": "base64",
          "media_type": "application/pdf",
          "data": "..."
        }
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
  "message": {
    "role": "user",
    "content": "This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion...\n\n1. User asked to find the branch...\n..."
  },
  "parentUuid": "86133565-..."
}
```

Always the immediate child of a `compact_boundary` system message.

---

## 2. Assistant Messages

All assistant messages have `message.model`, `message.id`, `message.usage`, `requestId`.

**Key streaming behavior**: A single API response (same `message.id`) is split across **multiple JSONL lines**, each containing exactly one content block. Each line gets its own `uuid` but shares the same `message.id`.

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
      "service_tier": "standard"
    }
  },
  "requestId": "req_011CYS..."
}
```

The `signature` is a protobuf-encoded cryptographic integrity check on thinking content.

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
      {
        "type": "text",
        "text": "Here are the branches related to Docker..."
      }
    ],
    "usage": { ... }
  }
}
```

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

| Block type | Fields |
|------------|--------|
| `thinking` | `thinking` (string), `signature` (base64) |
| `text` | `text` (string) |
| `tool_use` | `id`, `name`, `input` (object), `caller` |

---

## 3. System Messages

### 3a. compact_boundary

Marks a context compaction event. Creates a **new root** (`parentUuid: null`).

```json
{
  "type": "system",
  "subtype": "compact_boundary",
  "content": "Conversation compacted",
  "parentUuid": null,
  "logicalParentUuid": "d73c2ecb-...",
  "compactMetadata": {
    "trigger": "auto",
    "preTokens": 167393
  },
  "level": "info"
}
```

The next message is always a `user` with `isCompactSummary: true`.

### 3b. microcompact_boundary

Lighter-weight compaction that truncates large tool outputs without summarizing the full conversation.

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

Does NOT create a new root (parentUuid is normal).

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

---

## 4. Progress Messages

Streaming updates during tool execution. **Not sent to the API.**

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

### 4d. mcp_progress, waiting_for_task

Additional progress subtypes for MCP tool execution and background task polling.

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

No uuid/parentUuid. One per session file.

```json
{"type": "last-prompt",  "lastPrompt": "text",    "sessionId": "UUID4"}
{"type": "custom-title", "customTitle": "text",    "sessionId": "UUID4"}
{"type": "agent-name",   "agentName":  "name",     "sessionId": "UUID4"}
```

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

The `toolUseResult` top-level field on user messages carries tool-specific structured metadata **separate from** the `tool_result` content sent to the model.

### Per-tool schemas

| Tool | Key fields |
|------|------------|
| **Bash** | `stdout`, `stderr`, `interrupted`, `isImage`, `noOutputExpected`, `backgroundTaskId`, `persistedOutputPath`, `persistedOutputSize` |
| **Read** | `type: "text"`, `file: {filePath, content}` |
| **Write** | `type: "create"`, `filePath`, `content`, `originalFile: null` |
| **Edit** | `filePath`, `oldString`, `newString`, `replaceAll`, `originalFile`, `structuredPatch: [{oldStart, oldLines, newStart, newLines, lines}]` |
| **Glob** | `durationMs`, `filenames: [...]`, `numFiles`, `truncated` |
| **Grep** | `mode`, `numFiles`, `numLines`, `filenames`, `content`, `appliedLimit` |
| **Agent/Task** | `agentId`, `status`, `prompt`, `content`, `totalDurationMs`, `totalTokens`, `totalToolUseCount`, `usage`, `model` |
| **WebSearch** | `query`, `durationSeconds`, `results: [{tool_use_id, content: [{title, url}]}]` |
| **WebFetch** | `url`, `code`, `codeText`, `bytes`, `durationMs`, `result` |
| **TaskCreate** | `task: {id, subject}` |
| **TaskUpdate** | `success`, `taskId`, `updatedFields` |
| **LSP** | `operation`, `filePath`, `result`, `fileCount`, `resultCount` |
| **ToolSearch** | `query`, `matches: [...]`, `total_deferred_tools` |

---

## UUID Tree Structure

Messages form a **long linear chain** (not a bushy tree). Each message typically has one parent and one child.

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
- ~83% are `assistant → (progress + user)` — tool execution mechanics
- ~16% are `assistant → (assistant + user)` — streaming chunks
- ~1% are genuine conversation forks (user sent two different messages from the same point)

### After Compaction

Each compaction creates a **new root** that breaks the UUID chain:

```
compact_boundary (uuid=X, parentUuid=null, logicalParentUuid=old_msg)
  └─ user (uuid=Y, parentUuid=X, isCompactSummary=true)
      └─ assistant (uuid=Z, parentUuid=Y)   ← conversation continues
```

A session with 6 compactions has 7 root nodes (1 original + 6 compact_boundary).

### Forked Sessions

When a session is forked (`--fork-session` or `/fork`):
- The new JSONL file is a **complete copy** of a prefix of the parent
- **Every** message in the fork has `forkedFrom: {sessionId, messageUuid}`
- `forkedFrom.messageUuid` equals the message's own `uuid` (UUIDs are preserved)
- New messages (after the fork point) get fresh UUIDs without `forkedFrom`
- A `custom-title` entry records the fork lineage

---

## All 55 Top-Level Keys (Complete Inventory)

```
agentName, cause, compactMetadata, content, customTitle, cwd, data,
durationMs, entrypoint, error, forkedFrom, gitBranch, hasOutput,
hookCount, hookErrors, hookInfos, isApiErrorMessage, isCompactSummary,
isMeta, isSidechain, isSnapshotUpdate, isVisibleInTranscriptOnly,
lastPrompt, level, logicalParentUuid, maxRetries, mcpMeta, message,
messageId, microcompactMetadata, operation, parentToolUseID, parentUuid,
permissionMode, planContent, preventedContinuation, promptId, requestId,
retryAttempt, retryInMs, sessionId, slug, snapshot, sourceToolAssistantUUID,
sourceToolUseID, stopReason, subtype, teamName, thinkingMetadata,
timestamp, todos, toolUseID, toolUseResult, type, userType, uuid, version
```

---

## Editing Safety

| What | Safe? | Notes |
|------|-------|-------|
| Edit message text content | Yes | |
| Edit tool result content | Yes | |
| Delete whole lines | Yes | Maintain UUID chain |
| Append new messages | Yes | Generate valid UUIDs, link parentUuid |
| Delete progress lines | Yes | Not sent to API |
| Delete file-history-snapshot | Yes | Only affects undo |
| Delete queue-operation | Yes | Only affects input queue replay |
| Edit thinking content | Risky | Invalidates signature |
| Break UUID parentUuid chain | Bad | Orphans messages |
| Change sessionId | Bad | Session lookup fails |
| Reorder lines | Risky | Mostly chronological, minor deviations normal |
