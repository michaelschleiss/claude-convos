#!/usr/bin/env python3
"""Final follow-up: tool_reference context, non-null iterations/speed, caller='direct' always?"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

PROJECTS_DIR = Path.home() / ".config" / "claude" / "projects"


def find_jsonl_files():
    files = []
    for root, dirs, filenames in os.walk(PROJECTS_DIR):
        for fn in filenames:
            if fn.endswith(".jsonl"):
                files.append(os.path.join(root, fn))
    return files


def parse_jsonl(filepath):
    with open(filepath, "r", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except json.JSONDecodeError:
                pass


def main():
    files = find_jsonl_files()

    # 1. Find tool_reference blocks in tool_result content lists
    tool_ref_in_tool_result = 0
    tool_ref_outside = 0
    tool_ref_tool_names = Counter()
    tool_ref_full_example = None

    # 2. Non-null iterations/speed
    iterations_non_null = 0
    speed_non_null = 0
    iterations_non_null_example = None
    speed_non_null_example = None
    speed_values = Counter()

    # 3. tool_use blocks without caller field
    tool_use_no_caller = 0
    tool_use_no_caller_example = None

    # 4. Check if tool_result content list ever has mixed types
    tool_result_list_type_combos = Counter()

    # 5. Check for 'summary' entry type
    summary_count = 0
    summary_example = None

    for fi, filepath in enumerate(files):
        if fi % 200 == 0:
            print(f"  Processing file {fi+1}/{len(files)}...", file=sys.stderr)

        for lineno, entry in parse_jsonl(filepath):
            # summary type
            if entry.get("type") == "summary":
                summary_count += 1
                if summary_example is None:
                    summary_example = {"file": filepath, "line": lineno, "keys": list(entry.keys())}

            msg = entry.get("message")
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            content = msg.get("content")

            # Non-null iterations/speed
            if role == "assistant":
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    it = usage.get("iterations")
                    if it is not None:
                        iterations_non_null += 1
                        if iterations_non_null_example is None:
                            iterations_non_null_example = {"file": filepath, "line": lineno, "iterations": it}
                    sp = usage.get("speed")
                    if sp is not None:
                        speed_non_null += 1
                        speed_values[str(sp)] += 1
                        if speed_non_null_example is None:
                            speed_non_null_example = {"file": filepath, "line": lineno, "speed": sp}

            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")

                # tool_use without caller
                if btype == "tool_use" and "caller" not in block:
                    tool_use_no_caller += 1
                    if tool_use_no_caller_example is None:
                        tool_use_no_caller_example = {
                            "file": filepath, "line": lineno,
                            "name": block.get("name"),
                            "keys": list(block.keys())
                        }

                # tool_result content list analysis
                if btype == "tool_result":
                    tc = block.get("content")
                    if isinstance(tc, list):
                        types_in_list = tuple(sorted(set(
                            item.get("type") for item in tc if isinstance(item, dict)
                        )))
                        tool_result_list_type_combos[types_in_list] += 1

                        # Check for tool_reference in tool_result
                        for item in tc:
                            if isinstance(item, dict) and item.get("type") == "tool_reference":
                                tool_ref_in_tool_result += 1
                                tool_ref_tool_names[item.get("tool_name", "unknown")] += 1
                                if tool_ref_full_example is None:
                                    # Get the full tool_result block
                                    display_items = []
                                    for sub in tc[:5]:
                                        if isinstance(sub, dict):
                                            d = {}
                                            for k, v in sub.items():
                                                if isinstance(v, str) and len(v) > 200:
                                                    d[k] = v[:200] + "..."
                                                else:
                                                    d[k] = v
                                            display_items.append(d)
                                    tool_ref_full_example = {
                                        "file": filepath, "line": lineno,
                                        "role": role,
                                        "tool_use_id": block.get("tool_use_id"),
                                        "content_items": display_items,
                                        "total_items": len(tc)
                                    }

            # Also check top-level content for tool_reference (outside tool_result)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_reference":
                        # Check if this is NOT inside a tool_result
                        # (we're iterating top-level content blocks here)
                        if block.get("type") == "tool_reference":
                            tool_ref_outside += 1

    print("\n" + "=" * 80)
    print("FINAL FOLLOW-UP")
    print("=" * 80)

    print("\n--- tool_reference blocks ---")
    print(f"  In tool_result content: {tool_ref_in_tool_result}")
    print(f"  In top-level content (outside tool_result): {tool_ref_outside}")
    print(f"  Tool names referenced: {dict(tool_ref_tool_names.most_common())}")
    if tool_ref_full_example:
        print(f"  Full example:")
        print(f"    {json.dumps(tool_ref_full_example, indent=4, default=str)[:800]}")

    print("\n--- Non-null iterations ---")
    print(f"  Count: {iterations_non_null}")
    if iterations_non_null_example:
        print(f"  Example: {json.dumps(iterations_non_null_example)}")

    print("\n--- Non-null speed ---")
    print(f"  Count: {speed_non_null}")
    print(f"  Values: {dict(speed_values.most_common())}")
    if speed_non_null_example:
        print(f"  Example: {json.dumps(speed_non_null_example)}")

    print("\n--- tool_use without caller ---")
    print(f"  Count: {tool_use_no_caller}")
    if tool_use_no_caller_example:
        print(f"  Example: {json.dumps(tool_use_no_caller_example)}")

    print("\n--- tool_result content list type combos ---")
    for combo, count in tool_result_list_type_combos.most_common():
        print(f"  {combo}: {count}")

    print(f"\n--- 'summary' entry type: {summary_count} ---")
    if summary_example:
        print(f"  Example keys: {summary_example['keys']}")
        print(f"  File: {summary_example['file']}:{summary_example['line']}")


if __name__ == "__main__":
    main()
