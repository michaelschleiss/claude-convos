# Claude Code JSONL Session File Specification

Reverse-engineered from real session files, the Claude Code v2.1.81 JS bundle (127MB extracted),
and official/community documentation (2026-03-22).

Verified in two rounds: 8 agents against 1,698 files (244,990 entries), then 3 agents against
the decompiled source code. Not official Anthropic documentation.

Source: `github.com/michaelschleiss/claude-convos`

---

## File Location

```
~/.config/claude/projects/<encoded-project-path>/<session-id>.jsonl
~/.claude/projects/<encoded-project-path>/<session-id>.jsonl          (legacy)
```

`<encoded-project-path>` replaces all non-alphanumeric chars with `-` (e.g., `-home-user-myproject`).

### Session Discovery

Claude Code discovers sessions via **filesystem scan** (`readdirSync`), NOT from `sessions-index.json`.
The `NtH()` function filters for files where `basename(name, ".jsonl")` matches the UUID regex:
```
/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
```
Any conforming `.jsonl` file placed in a project directory will be discovered on next `--resume`.
`sessions-index.json` is an external cache — the binary contains zero references to it.

## Format

One JSON object per line (JSONL). Append-only log — compaction adds new entries but never deletes old ones.
No file-level checksums or integrity checks. No content validation on load beyond `JSON.parse` (failures silently skipped).

Files >5MB use a fast-path loader that scans for `"compact_boundary"` markers in 64KB chunks and
skips everything before the last boundary. A `FH_()` leaf-pruning pass at byte level further
reduces what gets parsed for large files (prunes non-leaf UUID chains if it would remove >50% of content).

---

## All Entry Types

### Transcript types (pass through `En()` filter into conversation)

| Type | Frequency | Purpose |
|------|-----------|---------|
| `progress` | ~61% | Streaming updates during tool/hook execution |
| `assistant` | ~20% | Claude's responses (thinking, text, tool_use) |
| `user` | ~14% | User messages and tool results |
| `system` | ~2% | Hook summaries, compaction, errors, turn timing |
| `attachment` | rare | Internal attachment messages (filtered by `Bg$` unless Anthropic-internal `"ant"` userType) |

### Metadata types (no UUID chain, parsed separately)

| Type | Purpose |
|------|---------|
| `file-history-snapshot` | File state snapshots for undo/rewind |
| `queue-operation` | User input queue (type-ahead) |
| `last-prompt` | Last user input for session restore (can appear multiple times) |
| `custom-title` | User-set session title |
| `ai-title` | AI-generated session title (`{type, aiTitle, sessionId}`) |
| `tag` | User-set session tag via `/tag` |
| `agent-name` | Named agent session identifier |
| `agent-color` | Agent color in team sessions |
| `agent-setting` | Agent settings |
| `mode` | Session mode (e.g., plan mode) |
| `worktree-state` | Git worktree session info |
| `pr-link` | Links session to a PR (`{prNumber, prUrl, prRepository}`) |
| `attribution-snapshot` | Attribution tracking |
| `speculation-accept` | Speculative decoding acceptance (`{timeSavedMs}`) |
| `content-replacement` | Content replacement records (`{agentId, replacements}`) |
| `marble-origami-commit` | Context collapse commit |
| `marble-origami-snapshot` | Context collapse snapshot |
| `summary` | Legacy compaction format (still parsed on load, zero instances in local data) |

The metadata markers used for fast pre-boundary scanning (`pH_` array):
`summary`, `custom-title`, `tag`, `agent-name`, `agent-color`, `agent-setting`, `mode`, `worktree-state`, `pr-link`.

---

## Common Envelope Fields

The `insertMessageChain` function adds these fields to every UUID-bearing entry:

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
  "timestamp":    "ISO8601",
  "slug":         "glimmering-hugging-nebula"
}
```

`isSidechain` is `true` on all entries in subagent session files. These also carry `agentId` (short hash).

Optional envelope fields:

| Field | When |
|-------|------|
| `slug` | Human-readable turn label (LLM-generated via embedded Pi agent, not a word list) |
| `teamName` | Present in team/agent contexts |
| `logicalParentUuid` | On `compact_boundary` — points to pre-compaction parent. May reference UUIDs no longer in file. |
| `entrypoint` | From `CLAUDE_CODE_ENTRYPOINT` env var |
| `forkedFrom` | `{sessionId, messageUuid}` — on every message in a forked session. `messageUuid` equals own `uuid`. |
| `agentId` | Short hash on subagent entries |
| `apiError` | Error string on some assistant entries (e.g., `"max_output_tokens"`) |
| `isMeta` | Boolean marking auto-generated/metadata messages |
| `promptId` | On some user messages |

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

`permissionMode` values: `"default"`, `"plan"`, `"acceptEdits"`, `"bypassPermissions"`, `"dontAsk"`, `"auto"`.

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

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_016hAvN...",
        "content": "output text...",
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
- **string** (~95%) — plain text output
- **array** (~5%) — list of blocks: `text`, `tool_reference`, or `image`
- **null** (rare)

`tool_result.is_error` is **only set on errors** (`true`). On success, the field is absent (not explicitly `false`).
Observed as explicitly `false` in ~43% of entries (older versions set it explicitly).

`tool_reference` blocks appear inside tool_result content arrays (from ToolSearch):
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
      { "type": "image", "source": { "type": "base64", "media_type": "image/jpeg", "data": "..." } }
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
      { "type": "document", "source": { "type": "base64", "media_type": "application/pdf", "data": "..." } }
    ]
  }
}
```

### 1f. Compaction summary

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

---

## 2. Assistant Messages

All assistant messages have `message.model`, `message.id`, `message.usage`, `requestId`.

A single API response (same `message.id`) is **split across multiple JSONL lines**, each typically
containing one content block. In rare cases (Haiku subagent), a single line may contain multiple `tool_use` blocks.

Assistant `message.content` is **always an array**, never a plain string (verified 47,858/47,858).

### Content block types

| Block type | Fields | Notes |
|------------|--------|-------|
| `thinking` | `thinking` (string), `signature` (base64) | Signature is cryptographic, described by Anthropic as "opaque". Not validated locally. |
| `redacted_thinking` | `data` (string) | API returns this when thinking content cannot be shown |
| `text` | `text` (string) | |
| `tool_use` | `id`, `name`, `input` (object), `caller` (optional) | |

`caller` values (from source): `"direct"`, `"code_execution"`, `"code_execution_20260120"`, `"code_execution_tool_result"`.
Absent ~28% of the time (older sessions, some MCP tools). When present, almost always `{"type": "direct"}`.

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
| `iterations` | Array or null |
| `speed` | `"standard"` |

### Synthetic messages

```json
{ "message": { "model": "<synthetic>", ... } }
```

---

## 3. System Messages

### 3a. compact_boundary

In non-forked sessions, creates a **new root** (`parentUuid: null`).
In forked sessions, `parentUuid` may be non-null (fork re-links to form single chain).

```json
{
  "type": "system",
  "subtype": "compact_boundary",
  "content": "Conversation compacted",
  "parentUuid": null,
  "logicalParentUuid": "d73c2ecb-...",
  "compactMetadata": {
    "trigger": "auto|manual",
    "preTokens": 167393,
    "preCompactDiscoveredTools": ["Bash", "Edit", "Read"],
    "userContext": "custom compaction instructions",
    "messagesSummarized": 42,
    "preservedSegment": {
      "headUuid": "...", "anchorUuid": "...", "tailUuid": "..."
    }
  },
  "level": "info"
}
```

**Auto-compact threshold** (from binary): `contextWindow - maxOutputTokenReservation(capped at 20K) - 13,000`.
For 200K context: ~167K. For 1M context: ~967K.

**preserved_segment** (optional): enables partial compaction where some messages are kept intact.
On load, `yH_()` relinks `head.parentUuid → anchorUuid`, redirects other anchor references to `tailUuid`,
zeroes usage on preserved assistant messages, and deletes non-preserved pre-boundary messages.

The next message is always `user` with `isCompactSummary: true` (verified 48/48).

### 3b. microcompact_boundary

Lighter-weight compaction that truncates large tool outputs. Does NOT create a new root.

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

Note: No creation code found in v2.1.81 bundle — feature may be dormant/replaced by `marble-origami-*`.
121 instances exist in local session data (from earlier versions). Disable with `DISABLE_MICROCOMPACT=1`.

### 3c–3f. Other observed subtypes

| Subtype | Purpose |
|---------|---------|
| `turn_duration` | `{durationMs, isMeta}` |
| `stop_hook_summary` | `{hookCount, hookInfos, hookErrors, preventedContinuation, stopReason, hasOutput, level}` |
| `api_error` | `{cause, error, retryInMs, retryAttempt, maxRetries, level}` |
| `local_command` | User ran `!command` or `/slash` |
| `api_retry` | API retry event |
| `init` | Session initialization (extensive: agents, apiKeySource, betas, tools, mcp_servers, model, etc.) |
| `interrupt` | User interrupted |

### 3g. Additional subtypes from source

Found in binary but not in local data:

`elicitation`, `elicitation_complete`, `hook_callback`, `hook_started`, `hook_progress`, `hook_response`,
`mcp_message`, `memory_saved`, `agents_killed`, `can_use_tool`, `set_permission_mode`, `status`,
`bridge_status`, `bridge_state`, `file_snapshot`, `task_notification`, `task_started`, `task_progress`,
`error_max_turns`, `error_max_budget_usd`, `error_max_structured_output_retries`, `success`, `error`,
`informational`, `stop_task`

SDK control-only subtypes (not directly written to JSONL):
`initialize`, `set_model`, `set_max_thinking_tokens`, `mcp_status`, `mcp_set_servers`, `mcp_reconnect`,
`mcp_toggle`, `rewind_files`, `cancel_async_message`, `apply_flag_settings`, `get_settings`

### System message `level` values

`"error"`, `"warn"`, `"warning"`, `"info"`, `"debug"`, `"suggestion"`, `"high"`, `"medium"`, `"low"`

---

## 4. Progress Messages

Streaming updates during tool execution. Participate in the UUID chain but are **not sent to the API**.

Ephemeral types (filtered out on load): `bash_progress`, `powershell_progress`, `mcp_progress`.

### All progress `data.type` values

| Subtype | Notes |
|---------|-------|
| `hook_progress` | `{hookEvent, hookName, command}` |
| `bash_progress` | `{output, fullOutput, elapsedTimeSeconds, totalLines, totalBytes, taskId}` |
| `agent_progress` | `{prompt, agentId, message, normalizedMessages}` |
| `mcp_progress` | MCP tool execution |
| `waiting_for_task` | Background task polling |
| `query_update` | Search query updates |
| `search_results_received` | Search results streaming |
| `skill_progress` | Skill tool execution |
| `powershell_progress` | Windows equivalent of bash_progress |

---

## 5–7. Non-UUID Entry Types

### File History Snapshot

```json
{
  "type": "file-history-snapshot",
  "messageId": "dfcedb63-...",
  "snapshot": { "messageId": "...", "trackedFileBackups": {}, "timestamp": "ISO8601" },
  "isSnapshotUpdate": false
}
```

### Queue Operations

```json
{
  "type": "queue-operation",
  "operation": "enqueue|dequeue|remove|popAll",
  "timestamp": "ISO8601",
  "sessionId": "UUID4",
  "content": "the queued message text"
}
```

### Metadata entries

```json
{"type": "last-prompt",  "lastPrompt": "text",   "sessionId": "UUID4"}
{"type": "custom-title", "customTitle": "text",   "sessionId": "UUID4"}
{"type": "ai-title",    "aiTitle":    "text",    "sessionId": "UUID4"}
{"type": "tag",          "tag":       "text",    "sessionId": "UUID4"}
{"type": "agent-name",   "agentName": "name",    "sessionId": "UUID4"}
```

---

## Tools (37 total from source)

### Built-in tools

| Tool | Aliases | Notes |
|------|---------|-------|
| **Bash** | — | |
| **Read** | — | |
| **Write** | — | |
| **Edit** | — | |
| **Glob** | — | Excluded when `EMBEDDED_SEARCH_TOOLS=true` |
| **Grep** | — | Excluded when `EMBEDDED_SEARCH_TOOLS=true` |
| **NotebookEdit** | — | Jupyter notebook cells |
| **WebSearch** | — | |
| **WebFetch** | — | |
| **Agent** | `Task` | `Task` is the newer name |
| **ToolSearch** | — | Deferred tool loader |
| **Skill** | — | Slash-command invocation |
| **LSP** | — | Code intelligence |
| **AskUserQuestion** | — | Multiple-choice prompt |
| **SendMessage** | — | Swarm teammate messaging |
| **SendUserMessage** | `Brief` | User-facing output channel |
| **TeamCreate** | — | |
| **TeamDelete** | — | |
| **TaskCreate** | — | |
| **TaskGet** | — | |
| **TaskUpdate** | — | |
| **TaskList** | — | |
| **TaskOutput** | `AgentOutputTool`, `BashOutputTool` | |
| **TaskStop** | `KillShell` | |
| **TodoWrite** | — | Session task checklist |
| **EnterPlanMode** | — | |
| **ExitPlanMode** | — | |
| **EnterWorktree** | — | |
| **ExitWorktree** | — | |
| **CronCreate** | — | |
| **CronDelete** | — | |
| **CronList** | — | |
| **RemoteTrigger** | — | Scheduled remote agent triggers |
| **StructuredOutput** | — | Return structured JSON (hidden from tool set) |
| **ListMcpResourcesTool** | — | List MCP server resources |
| **ReadMcpResourceTool** | — | Read MCP resource by URI |

Plus any dynamically registered MCP tools (`mcp__<server>__<tool>`).

### toolUseResult schemas

| Tool | Key fields |
|------|------------|
| **Bash** | `stdout`, `stderr`, `interrupted`, `isImage`, `noOutputExpected`, `backgroundTaskId`, `persistedOutputPath`, `persistedOutputSize`, `returnCodeInterpretation`, `assistantAutoBackgrounded`, `backgroundedByUser`, `tokenSaverOutput`, `rawOutputPath`, `structuredContent`, `dangerouslyDisableSandbox` |
| **Read** | `type` (`"text"` \| `"image"` \| `"pdf"` \| `"parts"` \| `"notebook"`), `file: {filePath, content}`, `dimensions` (for images) |
| **Write** | `type: "create"`, `filePath`, `content`, `originalFile`, `structuredPatch`, `gitDiff` |
| **Edit** | `filePath`, `oldString`, `newString`, `replaceAll`, `originalFile`, `structuredPatch`, `userModified`, `gitDiff` |
| **Glob** | `durationMs`, `filenames`, `numFiles`, `truncated` |
| **Grep** | `mode`, `numFiles`, `numLines`, `filenames`, `content`, `appliedLimit`, `appliedOffset` |
| **Agent/Task** | `agentId`, `status`, `prompt`, `content`, `totalDurationMs`, `totalTokens`, `totalToolUseCount`, `usage`, `model`, `agent_type`, `name`, `team_name`, `color`, `is_splitpane`, `plan_mode_required`, `outputFile`, `isAsync`, `canReadOutputFile`, `description`, `teammate_id`, `tmux_*` |
| **WebSearch** | `query`, `durationSeconds`, `results` |
| **WebFetch** | `url`, `code`, `codeText`, `bytes`, `durationMs`, `result` |
| **TaskCreate** | `task: {id, subject}`, `retrieval_status` |
| **TaskUpdate** | `success`, `taskId`, `updatedFields`, `statusChange`, `error`, `verificationNudgeNeeded` |
| **TaskList** | `tasks` |
| **TaskGet** | `task` |
| **TaskOutput** | `retrieval_status`, `task` |
| **TaskStop** | `task_id`, `task_type`, `command`, `message` |
| **LSP** | `operation`, `filePath`, `result`, `fileCount`, `resultCount` |
| **ToolSearch** | `query`, `matches`, `total_deferred_tools` |
| **Skill** | `success`, `commandName`, `allowedTools` |
| **AskUserQuestion** | `questions`, `answers`, `annotations` |
| **SendMessage** | `success`, `message`, `routing`, `request_id`, `target`, `recipients` |
| **SendUserMessage** | `message`, `attachments`, `sentAt` |
| **EnterPlanMode** | `message` |
| **ExitPlanMode** | `plan`, `filePath`, `hasTaskTool`, `isAgent` |
| **TeamCreate** | `lead_agent_id`, `team_file_path`, `team_name` |
| **TeamDelete** | `success`, `message`, `team_name` |
| **TodoWrite** | `newTodos`, `oldTodos`, `verificationNudgeNeeded` |
| **CronCreate** | `durable`, `humanSchedule`, `id`, `recurring` |
| **ListMcpResourcesTool** | `contents` |
| **ReadMcpResourceTool** | `contents: [{uri, mimeType, text, blobSavedTo}]` |
| **StructuredOutput** | (structured JSON per schema) |

---

## UUID Tree Structure

Messages form a **long linear chain** (~85-94% of nodes have exactly one child). Max branching factor is 2.

### Branch points

- **~84%** `assistant → (progress + user)` — tool execution mechanics
- **~15%** `assistant → (assistant + user)` — streaming chunks
- **~1%** genuine conversation forks

### Message ordering

99.5%+ chronological. The UUID chain reconstruction (`xtH()`) walks `parentUuid` links, not line order.
Cycle detection via `Set` — breaks on cycle, logs `tengu_chain_parent_cycle`.
`hH_()` post-processor splices sibling assistant messages sharing the same `message.id`.

### After Compaction

Non-forked: each compaction creates a **new root** (`parentUuid: null`).
Forked: compact_boundary entries are re-parented to preceding entry (single-rooted chain).

### Forked Sessions

- New file = complete prefix copy of parent, every message has `forkedFrom: {sessionId, messageUuid}`
- `forkedFrom.messageUuid` equals own `uuid` (UUIDs preserved verbatim)
- Fork re-links compact_boundary parentUuids
- A `custom-title` entry records fork lineage

### Session Continuation (distinct from forking)

When context exhausted via `--continue`, new file starts with prefix copy (parent's sessionId).
Own session begins where sessionId changes. Both files share the same `slug`. No `forkedFrom`.

---

## Editing Safety

| What | Safe? | Notes |
|------|-------|-------|
| Edit message text content | Yes | No content validation |
| Edit tool result content | Yes | No validation |
| Delete whole lines | Mostly | Re-link children's parentUuid to deleted node's parent |
| Append new messages | Yes | Valid UUID, chain parentUuid correctly |
| Delete progress lines | Mostly | Safe if no message references it as parentUuid (progress participates in chain) |
| Delete file-history-snapshot | Yes | Only affects undo/rewind |
| Delete queue-operation | Yes | Only affects input queue |
| Edit thinking content | Risky | Not validated locally; API rejects modified thinking |
| Break UUID parentUuid chain | Tolerated | Chain stops at break; earlier messages invisible, no crash |
| Change sessionId | Bad | Many lookups index by sessionId |
| Reorder lines | Mostly safe | Chain uses parentUuid not line order. Metadata uses `findLast`. |
| Add new .jsonl file | Works | Filesystem scan discovers any UUID-named .jsonl |

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
| `CLAUDE_CODE_DISABLE_PRECOMPACT_SKIP` | Disable fast-path compact_boundary skip for large files |
| `CLAUDE_CODE_ENTRYPOINT` | Sets `entrypoint` field on messages |

## All Top-Level Keys (59 verified)

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
