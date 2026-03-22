#!/usr/bin/env python3
"""Correlate unknown toolUseResult entries back to their tool names via sourceToolUseID."""

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
print(f"Scanning {len(files)} files to correlate toolUseResult with tool names...")

# Per-file: build tool_use_id -> tool_name map, then match toolUseResults
tool_result_by_name = defaultdict(lambda: defaultdict(int))  # tool_name -> field -> count
tool_result_count_by_name = Counter()

# Also track: Write toolUseResult - does it have the fields the spec says?
write_results = []

# Track tool_result content that is an array - what block types per tool?
array_content_by_tool = defaultdict(Counter)

fcount = 0
for fpath in files:
    fcount += 1
    if fcount % 200 == 0:
        print(f"  ... {fcount}/{len(files)}", file=sys.stderr)

    entries = list(parse_jsonl(fpath))

    # Build map: tool_use_id -> tool_name
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

    # Now match user entries with toolUseResult
    for e in entries:
        if e.get("type") != "user":
            continue

        tur = e.get("toolUseResult")
        source_id = e.get("sourceToolUseID", "")

        if tur and isinstance(tur, dict):
            tool_name = tool_id_to_name.get(source_id, "<no-match>")
            tool_result_count_by_name[tool_name] += 1
            for k in tur:
                tool_result_by_name[tool_name][k] += 1

            if tool_name == "Write" and len(write_results) < 5:
                example = {}
                for k, v in tur.items():
                    sv = str(v)
                    example[k] = sv[:150] + "..." if len(sv) > 150 else v
                write_results.append({"fields": sorted(tur.keys()), "example": example})

        # Also track tool_result content arrays per tool
        msg = e.get("message", {})
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    rc = block.get("content")
                    tid = block.get("tool_use_id", "")
                    tname = tool_id_to_name.get(tid, "<no-match>")
                    if isinstance(rc, list):
                        for item in rc:
                            if isinstance(item, dict):
                                array_content_by_tool[tname][item.get("type", "<no-type>")] += 1

print(f"\n{'='*80}")
print("CORRELATED toolUseResult SCHEMAS (by tool name from sourceToolUseID)")
print(f"{'='*80}")

for name, count in sorted(tool_result_count_by_name.items(), key=lambda x: -x[1]):
    fields = sorted(tool_result_by_name[name].keys())
    print(f"\n  {name} ({count} results)")
    print(f"    Fields: {fields}")
    for f in fields:
        print(f"      {f}: {tool_result_by_name[name][f]}")

print(f"\n{'='*80}")
print("Write toolUseResult examples")
print(f"{'='*80}")
for w in write_results:
    print(f"  fields: {w['fields']}")
    print(f"  example: {json.dumps(w['example'], indent=4)[:400]}")
    print()

print(f"\n{'='*80}")
print("tool_result ARRAY CONTENT by tool")
print(f"{'='*80}")
for tname in sorted(array_content_by_tool.keys()):
    print(f"  {tname}: {dict(array_content_by_tool[tname])}")

print("\nDone.")
