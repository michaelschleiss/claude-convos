#!/usr/bin/env python3
"""Audit tool_use and toolUseResult schemas across all Claude Code JSONL session files."""

import json
import os
import sys
from collections import defaultdict, Counter
from pathlib import Path

BASE = Path.home() / ".config" / "claude" / "projects"

def find_all_jsonl():
    """Find all JSONL session files."""
    files = []
    for root, dirs, fnames in os.walk(BASE):
        for f in fnames:
            if f.endswith(".jsonl"):
                files.append(os.path.join(root, f))
    return files

def parse_jsonl(path):
    """Yield parsed JSON objects from a JSONL file."""
    with open(path, "r", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                pass

# ─── Collectors ───────────────────────────────────────────────────────────

# 1. All distinct tool names and their input field sets
tool_input_fields = defaultdict(lambda: defaultdict(int))  # tool -> field -> count
tool_use_count = Counter()  # tool -> count

# 2. toolUseResult schemas per tool
tool_result_fields = defaultdict(lambda: defaultdict(int))  # tool -> field -> count
tool_result_count = Counter()

# 3. Multi-tool_use entries (more than one tool_use in a single JSONL line)
multi_tool_entries = []

# 4. tool_result content format (string vs array, and block types if array)
tool_result_content_formats = Counter()
tool_result_content_block_types = Counter()

# 5. is_error=true examples
error_results = []

# 6. caller field values
caller_values = Counter()

# 7. tool_result "content" type per tool
tool_result_content_type_per_tool = defaultdict(Counter)

# 8. Example entries for each tool (store first seen)
tool_use_examples = {}
tool_result_examples = {}

# ─── Scan ─────────────────────────────────────────────────────────────────

files = find_all_jsonl()
print(f"Scanning {len(files)} JSONL files...")

file_count = 0
entry_count = 0
assistant_entries = 0
user_entries = 0

for fpath in files:
    file_count += 1
    if file_count % 200 == 0:
        print(f"  ... processed {file_count}/{len(files)} files", file=sys.stderr)

    for entry in parse_jsonl(fpath):
        entry_count += 1
        etype = entry.get("type")

        # ── ASSISTANT: tool_use blocks ──
        if etype == "assistant":
            assistant_entries += 1
            msg = entry.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                tool_uses_in_entry = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_uses_in_entry.append(block)
                        name = block.get("name", "<unknown>")
                        tool_use_count[name] += 1

                        # Collect input fields
                        inp = block.get("input", {})
                        if isinstance(inp, dict):
                            for k in inp:
                                tool_input_fields[name][k] += 1

                        # Collect caller field
                        caller = block.get("caller")
                        if caller is not None:
                            caller_str = json.dumps(caller, sort_keys=True)
                            caller_values[caller_str] += 1
                        else:
                            caller_values["<absent>"] += 1

                        # Store example
                        if name not in tool_use_examples:
                            tool_use_examples[name] = {
                                "name": name,
                                "input_keys": sorted(inp.keys()) if isinstance(inp, dict) else str(type(inp)),
                                "caller": caller,
                                "id": block.get("id", ""),
                                "file": fpath,
                            }

                # Check for multiple tool_use blocks in one entry
                if len(tool_uses_in_entry) > 1:
                    multi_tool_entries.append({
                        "file": fpath,
                        "count": len(tool_uses_in_entry),
                        "tools": [t.get("name") for t in tool_uses_in_entry],
                        "message_id": msg.get("id", ""),
                    })

        # ── USER: tool_result blocks + toolUseResult ──
        if etype == "user":
            user_entries += 1
            msg = entry.get("message", {})
            content = msg.get("content", [])

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_content = block.get("content")
                        is_error = block.get("is_error", False)

                        # Content format
                        if isinstance(result_content, str):
                            tool_result_content_formats["string"] += 1
                        elif isinstance(result_content, list):
                            tool_result_content_formats["array"] += 1
                            for item in result_content:
                                if isinstance(item, dict):
                                    tool_result_content_block_types[item.get("type", "<no-type>")] += 1
                        elif result_content is None:
                            tool_result_content_formats["null"] += 1
                        else:
                            tool_result_content_formats[f"other:{type(result_content).__name__}"] += 1

                        # is_error examples
                        if is_error:
                            if len(error_results) < 20:
                                error_results.append({
                                    "file": fpath,
                                    "tool_use_id": block.get("tool_use_id", ""),
                                    "content_preview": str(result_content)[:300] if result_content else None,
                                    "is_error": is_error,
                                })

            # toolUseResult
            tur = entry.get("toolUseResult")
            if tur and isinstance(tur, dict):
                # Figure out which tool this belongs to by looking at sourceToolUseID
                # or by inspecting the toolUseResult keys
                tool_name = tur.get("tool") or tur.get("toolName") or "<inferred>"

                # If we can't get tool name from tur, try to infer from field patterns
                if tool_name == "<inferred>":
                    keys = set(tur.keys())
                    if "stdout" in keys or "stderr" in keys:
                        tool_name = "Bash"
                    elif "filePath" in keys and "structuredPatch" in keys:
                        tool_name = "Edit"
                    elif "filePath" in keys and "originalFile" in keys and "structuredPatch" not in keys:
                        tool_name = "Write"
                    elif keys == {"type", "file"} or ({"type", "file"} <= keys and tur.get("type") == "text"):
                        tool_name = "Read"
                    elif "filenames" in keys and "numFiles" in keys and "durationMs" in keys and "numLines" not in keys:
                        tool_name = "Glob"
                    elif "numLines" in keys or "mode" in keys:
                        tool_name = "Grep"
                    elif "agentId" in keys:
                        tool_name = "Agent"
                    elif "query" in keys and "results" in keys:
                        tool_name = "WebSearch"
                    elif "url" in keys and "code" in keys:
                        tool_name = "WebFetch"
                    elif "task" in keys:
                        tool_name = "TaskCreate"
                    elif "success" in keys and "taskId" in keys:
                        tool_name = "TaskUpdate"
                    elif "operation" in keys and "resultCount" in keys:
                        tool_name = "LSP"
                    elif "matches" in keys and "total_deferred_tools" in keys:
                        tool_name = "ToolSearch"
                    else:
                        tool_name = f"<unknown:{sorted(keys)[:5]}>"

                tool_result_count[tool_name] += 1
                for k in tur:
                    tool_result_fields[tool_name][k] += 1

                if tool_name not in tool_result_examples:
                    # Truncate large values for the example
                    example = {}
                    for k, v in tur.items():
                        sv = str(v)
                        if len(sv) > 200:
                            example[k] = sv[:200] + "..."
                        else:
                            example[k] = v
                    tool_result_examples[tool_name] = {
                        "tool": tool_name,
                        "fields": sorted(tur.keys()),
                        "example": example,
                        "file": fpath,
                    }

# ─── Report ───────────────────────────────────────────────────────────────

print(f"\n{'='*80}")
print(f"TOOL AUDIT REPORT")
print(f"{'='*80}")
print(f"Files scanned:     {file_count}")
print(f"Total entries:     {entry_count}")
print(f"Assistant entries:  {assistant_entries}")
print(f"User entries:       {user_entries}")

print(f"\n{'─'*80}")
print("1. ALL DISTINCT TOOL NAMES (from tool_use blocks)")
print(f"{'─'*80}")
for name, count in sorted(tool_use_count.items(), key=lambda x: -x[1]):
    fields = sorted(tool_input_fields[name].keys())
    print(f"\n  {name} ({count} uses)")
    print(f"    Input fields: {fields}")
    for f in fields:
        print(f"      {f}: seen {tool_input_fields[name][f]} times")

print(f"\n{'─'*80}")
print("2. toolUseResult SCHEMAS (per inferred tool)")
print(f"{'─'*80}")
for name, count in sorted(tool_result_count.items(), key=lambda x: -x[1]):
    fields = sorted(tool_result_fields[name].keys())
    print(f"\n  {name} ({count} results)")
    print(f"    Fields: {fields}")
    for f in fields:
        print(f"      {f}: seen {tool_result_fields[name][f]} times")

print(f"\n{'─'*80}")
print("3. MULTI-TOOL_USE ENTRIES (>1 tool_use in single JSONL line)")
print(f"{'─'*80}")
print(f"  Count: {len(multi_tool_entries)}")
if multi_tool_entries:
    for e in multi_tool_entries[:10]:
        print(f"    {e['count']} tools: {e['tools']} (msg_id={e['message_id'][:20]}...)")
        print(f"      File: {e['file']}")

print(f"\n{'─'*80}")
print("4. tool_result CONTENT FORMATS")
print(f"{'─'*80}")
for fmt, count in sorted(tool_result_content_formats.items(), key=lambda x: -x[1]):
    print(f"  {fmt}: {count}")
if tool_result_content_block_types:
    print(f"  Array block types:")
    for bt, count in sorted(tool_result_content_block_types.items(), key=lambda x: -x[1]):
        print(f"    {bt}: {count}")

print(f"\n{'─'*80}")
print("5. is_error=true EXAMPLES")
print(f"{'─'*80}")
print(f"  Total error results captured: {len(error_results)}")
for e in error_results[:10]:
    print(f"\n  tool_use_id: {e['tool_use_id']}")
    print(f"  content_preview: {e['content_preview']}")
    print(f"  file: {e['file']}")

print(f"\n{'─'*80}")
print("6. CALLER FIELD VALUES")
print(f"{'─'*80}")
for val, count in sorted(caller_values.items(), key=lambda x: -x[1]):
    print(f"  {val}: {count}")

print(f"\n{'─'*80}")
print("7. TOOLS IN DATA BUT NOT IN SPEC")
print(f"{'─'*80}")
spec_tools = {
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "Agent",
    "WebSearch", "WebFetch", "TaskCreate", "TaskUpdate", "LSP", "ToolSearch",
}
all_tools = set(tool_use_count.keys())
extra = all_tools - spec_tools
missing = spec_tools - all_tools
print(f"  Tools in data not in spec toolUseResult table: {sorted(extra) if extra else 'none'}")
print(f"  Tools in spec but not seen in data: {sorted(missing) if missing else 'none'}")

print(f"\n{'─'*80}")
print("8. TOOL USE EXAMPLES (first seen per tool)")
print(f"{'─'*80}")
for name in sorted(tool_use_examples.keys()):
    ex = tool_use_examples[name]
    print(f"\n  {name}:")
    print(f"    input_keys: {ex['input_keys']}")
    print(f"    caller: {ex['caller']}")

print(f"\n{'─'*80}")
print("9. toolUseResult EXAMPLES (first seen per tool)")
print(f"{'─'*80}")
for name in sorted(tool_result_examples.keys()):
    ex = tool_result_examples[name]
    print(f"\n  {name}:")
    print(f"    fields: {ex['fields']}")

print("\n\nDone.")
