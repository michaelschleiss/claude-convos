#!/usr/bin/env python3
"""Audit tool_use and toolUseResult - improved correlation and Write schema detection."""

import json
import os
import sys
from collections import defaultdict, Counter
from pathlib import Path

BASE = Path.home() / ".config" / "claude" / "projects"

def find_all_jsonl():
    files = []
    for root, dirs, fnames in os.walk(BASE):
        for f in fnames:
            if f.endswith(".jsonl"):
                files.append(os.path.join(root, f))
    return files

def parse_jsonl(path):
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                pass

files = find_all_jsonl()
print(f"Scanning {len(files)} files...", file=sys.stderr)

# Collectors
write_tur_examples = []
write_tur_fields = Counter()
write_tur_count = 0

# For correlating: within each file build tool_use_id->name map using the "id" field in tool_use blocks
correlated_tur_fields = defaultdict(lambda: defaultdict(int))
correlated_tur_count = Counter()

# Track tool_reference blocks
tool_reference_examples = []

# Track entries where content is array with multiple block types
multi_block_tool_results = []

# Check the "model" field on Agent toolUseResult
agent_model_values = Counter()

# SendMessage toolUseResult
sendmsg_tur_fields = Counter()
sendmsg_tur_count = 0
sendmsg_tur_examples = []

# Skill toolUseResult
skill_tur_examples = []

# TaskList, TaskGet, TaskOutput, TaskStop, ExitPlanMode, EnterPlanMode toolUseResults
misc_tur = defaultdict(list)

fcount = 0
for fpath in files:
    fcount += 1
    if fcount % 200 == 0:
        print(f"  ... {fcount}/{len(files)}", file=sys.stderr)

    entries = list(parse_jsonl(fpath))

    # Build map: tool_use "id" -> tool_name
    # The tool_use block has "id" field (e.g. "toolu_016hAvN...")
    tool_id_to_name = {}
    for e in entries:
        if e.get("type") == "assistant":
            msg = e.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tid = block.get("id", "")
                        tname = block.get("name", "<unknown>")
                        if tid:
                            tool_id_to_name[tid] = tname

    for e in entries:
        if e.get("type") != "user":
            continue

        tur = e.get("toolUseResult")
        source_id = e.get("sourceToolUseID", "")

        # Also check tool_result block's tool_use_id
        msg = e.get("message", {})
        content = msg.get("content", [])
        tr_tool_use_id = None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tr_tool_use_id = block.get("tool_use_id", "")

                    # Check for tool_reference blocks
                    rc = block.get("content")
                    if isinstance(rc, list):
                        for item in rc:
                            if isinstance(item, dict) and item.get("type") == "tool_reference":
                                if len(tool_reference_examples) < 5:
                                    ex = {}
                                    for k, v in item.items():
                                        sv = str(v)
                                        ex[k] = sv[:200] + "..." if len(sv) > 200 else v
                                    tool_reference_examples.append(ex)

        # Determine tool name
        tool_name = tool_id_to_name.get(source_id) or tool_id_to_name.get(tr_tool_use_id) or None

        if tur and isinstance(tur, dict):
            if tool_name:
                correlated_tur_count[tool_name] += 1
                for k in tur:
                    correlated_tur_fields[tool_name][k] += 1
            else:
                correlated_tur_count["<no-match>"] += 1
                for k in tur:
                    correlated_tur_fields["<no-match>"][k] += 1

            # Specific tool tracking
            if tool_name == "Write":
                write_tur_count += 1
                for k in tur:
                    write_tur_fields[k] += 1
                if len(write_tur_examples) < 5:
                    ex = {}
                    for k, v in tur.items():
                        sv = str(v)
                        ex[k] = sv[:200] + "..." if len(sv) > 200 else v
                    write_tur_examples.append(ex)

            if tool_name == "Agent":
                m = tur.get("model")
                if m:
                    agent_model_values[m] += 1

            if tool_name == "SendMessage":
                sendmsg_tur_count += 1
                for k in tur:
                    sendmsg_tur_fields[k] += 1
                if len(sendmsg_tur_examples) < 3:
                    ex = {}
                    for k, v in tur.items():
                        sv = str(v)
                        ex[k] = sv[:150] + "..." if len(sv) > 150 else v
                    sendmsg_tur_examples.append(ex)

            if tool_name == "Skill" and len(skill_tur_examples) < 3:
                ex = {}
                for k, v in tur.items():
                    sv = str(v)
                    ex[k] = sv[:200] + "..." if len(sv) > 200 else v
                skill_tur_examples.append(ex)

            if tool_name in ("TaskList", "TaskGet", "TaskOutput", "TaskStop",
                             "ExitPlanMode", "EnterPlanMode", "TodoWrite",
                             "AskUserQuestion", "CronCreate", "TeamCreate",
                             "TeamDelete", "EnterWorktree"):
                if len(misc_tur[tool_name]) < 2:
                    ex = {}
                    for k, v in tur.items():
                        sv = str(v)
                        ex[k] = sv[:200] + "..." if len(sv) > 200 else v
                    misc_tur[tool_name].append({"fields": sorted(tur.keys()), "example": ex})


# ─── Report ───────────────────────────────────────────────────────────────

print(f"\n{'='*80}")
print("CORRELATED toolUseResult SCHEMAS")
print(f"{'='*80}")

for name, count in sorted(correlated_tur_count.items(), key=lambda x: -x[1]):
    if name == "<no-match>":
        continue
    fields = sorted(correlated_tur_fields[name].keys())
    print(f"\n  {name} ({count} results)")
    print(f"    Fields: {fields}")
    for f in fields:
        print(f"      {f}: {correlated_tur_fields[name][f]}")

no_match = correlated_tur_count.get("<no-match>", 0)
if no_match:
    print(f"\n  <no-match>: {no_match} toolUseResult entries could not be correlated")

print(f"\n{'='*80}")
print("Write toolUseResult")
print(f"{'='*80}")
print(f"  Count: {write_tur_count}")
print(f"  Fields: {dict(write_tur_fields)}")
for w in write_tur_examples:
    print(f"  Example: {json.dumps(w, indent=2)[:500]}")
    print()

print(f"\n{'='*80}")
print("SendMessage toolUseResult")
print(f"{'='*80}")
print(f"  Count: {sendmsg_tur_count}")
print(f"  Fields: {dict(sendmsg_tur_fields)}")
for s in sendmsg_tur_examples:
    print(f"  Example: {json.dumps(s, indent=2)[:400]}")
    print()

print(f"\n{'='*80}")
print("Skill toolUseResult")
print(f"{'='*80}")
for s in skill_tur_examples:
    print(f"  fields: {sorted(s.keys())}")
    print(f"  example: {json.dumps(s, indent=2)[:400]}")
    print()

print(f"\n{'='*80}")
print("Misc tool toolUseResult schemas")
print(f"{'='*80}")
for tname in sorted(misc_tur.keys()):
    for ex in misc_tur[tname]:
        print(f"\n  {tname}:")
        print(f"    fields: {ex['fields']}")

print(f"\n{'='*80}")
print("tool_reference block examples")
print(f"{'='*80}")
for tr in tool_reference_examples:
    print(f"  {json.dumps(tr, indent=2)[:300]}")
    print()

print(f"\n{'='*80}")
print("Agent model values")
print(f"{'='*80}")
for m, c in sorted(agent_model_values.items(), key=lambda x: -x[1]):
    print(f"  {m}: {c}")

print("\nDone.")
