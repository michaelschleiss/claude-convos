#!/usr/bin/env python3
"""Follow-up audit: detailed examples for undocumented usage fields, caller variants, tool_result is_error."""

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
    print(f"Found {len(files)} JSONL files")

    # Track examples of undocumented usage fields
    server_tool_use_example = None
    iterations_example = None
    speed_example = None
    inference_geo_values = Counter()

    # Track caller field variants
    caller_types = Counter()
    caller_examples = {}

    # Track is_error field on tool_result
    is_error_true_count = 0
    is_error_false_count = 0
    is_error_missing_count = 0
    is_error_true_example = None

    # Track tool_result content types (string vs list vs missing)
    tool_result_content_types = Counter()
    tool_result_content_list_example = None

    # Track document source types and media_types
    doc_media_types = Counter()
    image_media_types = Counter()
    image_source_types = Counter()
    doc_source_types = Counter()

    # Check for "redacted_thinking" blocks (known Anthropic variant)
    redacted_thinking_count = 0

    for fi, filepath in enumerate(files):
        if fi % 200 == 0:
            print(f"  Processing file {fi+1}/{len(files)}...", file=sys.stderr)

        for lineno, entry in parse_jsonl(filepath):
            msg = entry.get("message")
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            content = msg.get("content")

            # Usage fields
            if role == "assistant":
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    if "server_tool_use" in usage and server_tool_use_example is None:
                        server_tool_use_example = {
                            "file": filepath, "line": lineno,
                            "server_tool_use": usage["server_tool_use"]
                        }
                    if "iterations" in usage and iterations_example is None:
                        iterations_example = {
                            "file": filepath, "line": lineno,
                            "iterations": usage["iterations"]
                        }
                    if "speed" in usage and speed_example is None:
                        speed_example = {
                            "file": filepath, "line": lineno,
                            "speed": usage["speed"]
                        }
                    geo = usage.get("inference_geo")
                    if geo is not None:
                        inference_geo_values[str(geo)] += 1

            # Scan content blocks
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")

                    # Caller variants on tool_use
                    if btype == "tool_use":
                        caller = block.get("caller")
                        if caller is not None:
                            ctype = caller.get("type") if isinstance(caller, dict) else str(caller)
                            caller_types[ctype] += 1
                            if ctype not in caller_examples:
                                caller_examples[ctype] = {
                                    "file": filepath, "line": lineno,
                                    "caller": caller
                                }

                    # tool_result is_error
                    if btype == "tool_result":
                        if "is_error" in block:
                            if block["is_error"]:
                                is_error_true_count += 1
                                if is_error_true_example is None:
                                    tc = block.get("content", "")
                                    is_error_true_example = {
                                        "file": filepath, "line": lineno,
                                        "content_snippet": tc[:200] if isinstance(tc, str) else str(tc)[:200]
                                    }
                            else:
                                is_error_false_count += 1
                        else:
                            is_error_missing_count += 1

                        # Content type for tool_result
                        tc = block.get("content")
                        if tc is None:
                            tool_result_content_types["None/missing"] += 1
                        elif isinstance(tc, str):
                            tool_result_content_types["string"] += 1
                        elif isinstance(tc, list):
                            tool_result_content_types["list"] += 1
                            if tool_result_content_list_example is None:
                                # Truncate nested data
                                display = []
                                for item in tc[:3]:
                                    if isinstance(item, dict):
                                        d = {}
                                        for k, v in item.items():
                                            if isinstance(v, str) and len(v) > 100:
                                                d[k] = v[:100] + "..."
                                            else:
                                                d[k] = v
                                        display.append(d)
                                    else:
                                        display.append(item)
                                tool_result_content_list_example = {
                                    "file": filepath, "line": lineno,
                                    "items_count": len(tc),
                                    "items_preview": display
                                }
                        else:
                            tool_result_content_types[type(tc).__name__] += 1

                    # Image/document source details
                    if btype == "image":
                        src = block.get("source", {})
                        if isinstance(src, dict):
                            image_source_types[src.get("type")] += 1
                            image_media_types[src.get("media_type")] += 1
                    if btype == "document":
                        src = block.get("source", {})
                        if isinstance(src, dict):
                            doc_source_types[src.get("type")] += 1
                            doc_media_types[src.get("media_type")] += 1

                    # Redacted thinking
                    if btype == "redacted_thinking":
                        redacted_thinking_count += 1

    # Report
    print("\n" + "=" * 80)
    print("FOLLOW-UP AUDIT REPORT")
    print("=" * 80)

    print("\n--- server_tool_use field ---")
    if server_tool_use_example:
        print(f"  Example: {json.dumps(server_tool_use_example, indent=2)}")
    else:
        print("  Not found.")

    print("\n--- iterations field ---")
    if iterations_example:
        print(f"  Example: {json.dumps(iterations_example, indent=2)}")
    else:
        print("  Not found.")

    print("\n--- speed field ---")
    if speed_example:
        print(f"  Example: {json.dumps(speed_example, indent=2)}")
    else:
        print("  Not found.")

    print("\n--- inference_geo values ---")
    for geo, count in inference_geo_values.most_common():
        print(f"  {geo}: {count}")

    print("\n--- tool_use caller types ---")
    for ctype, count in caller_types.most_common():
        print(f"  {ctype}: {count}")
        ex = caller_examples.get(ctype)
        if ex:
            print(f"    example: {json.dumps(ex['caller'])}")

    print("\n--- tool_result is_error ---")
    print(f"  is_error=true:    {is_error_true_count}")
    print(f"  is_error=false:   {is_error_false_count}")
    print(f"  is_error missing: {is_error_missing_count}")
    if is_error_true_example:
        print(f"  Error example: {is_error_true_example['file']}:{is_error_true_example['line']}")
        print(f"    content: {is_error_true_example['content_snippet'][:200]}")

    print("\n--- tool_result content types ---")
    for ctype, count in tool_result_content_types.most_common():
        print(f"  {ctype}: {count}")
    if tool_result_content_list_example:
        print(f"  List example: {tool_result_content_list_example['file']}:{tool_result_content_list_example['line']}")
        print(f"    items count: {tool_result_content_list_example['items_count']}")
        print(f"    preview: {json.dumps(tool_result_content_list_example['items_preview'], indent=2, default=str)[:500]}")

    print("\n--- Image source types & media types ---")
    print(f"  source types: {dict(image_source_types)}")
    print(f"  media types: {dict(image_media_types)}")

    print("\n--- Document source types & media types ---")
    print(f"  source types: {dict(doc_source_types)}")
    print(f"  media types: {dict(doc_media_types)}")

    print(f"\n--- Redacted thinking blocks: {redacted_thinking_count} ---")

    print("\n" + "=" * 80)
    print("FOLLOW-UP COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
