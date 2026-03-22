#!/usr/bin/env python3
"""
Audit all Claude Code JSONL session files for content block types and message.content formats.
Addresses all 10 verification points from task #7.
"""

import json
import os
import sys
from collections import defaultdict, Counter
from pathlib import Path

PROJECTS_DIR = Path.home() / ".config" / "claude" / "projects"


def find_jsonl_files():
    """Find all .jsonl files under the projects directory."""
    files = []
    for root, dirs, filenames in os.walk(PROJECTS_DIR):
        for fn in filenames:
            if fn.endswith(".jsonl"):
                files.append(os.path.join(root, fn))
    return files


def parse_jsonl(filepath):
    """Parse a JSONL file, yielding (line_number, entry) tuples."""
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

    # --- Accumulators ---
    # 1. All distinct content block types
    content_block_types = Counter()  # type_name -> count
    block_type_by_role = defaultdict(Counter)  # role -> {type_name -> count}

    # 2. User content formats: string vs array
    user_content_string_count = 0
    user_content_array_count = 0
    user_content_string_example = None
    user_content_array_example = None

    # 3. Assistant content format: string vs array
    assistant_content_string_count = 0
    assistant_content_array_count = 0
    assistant_content_string_example = None

    # 4. Image blocks
    image_block_count = 0
    image_block_example = None

    # 5. Document blocks
    document_block_count = 0
    document_block_example = None

    # 6. tool_reference blocks
    tool_reference_count = 0
    tool_reference_example = None

    # 7. Undocumented content block types
    KNOWN_BLOCK_TYPES = {"text", "thinking", "tool_use", "tool_result", "image", "document"}
    unknown_block_types = defaultdict(list)  # type_name -> [(file, line)]

    # 8. Thinking block signature
    thinking_with_signature = 0
    thinking_without_signature = 0
    thinking_sig_not_base64 = 0
    thinking_example = None

    # 9. Text blocks with structured data
    text_with_json = 0
    text_with_markdown_table = 0
    text_block_total = 0

    # 10. Assistant usage fields
    usage_fields = Counter()  # field_name -> count
    usage_cache_creation_fields = Counter()
    usage_example = None
    has_server_tool_use = 0
    has_iterations = 0
    has_speed = 0

    # Extra accumulators
    content_block_fields_by_type = defaultdict(lambda: Counter())  # block_type -> {field -> count}
    total_entries = 0
    entry_type_counts = Counter()

    for fi, filepath in enumerate(files):
        if fi % 200 == 0:
            print(f"  Processing file {fi+1}/{len(files)}...", file=sys.stderr)

        for lineno, entry in parse_jsonl(filepath):
            total_entries += 1
            entry_type = entry.get("type")
            entry_type_counts[entry_type] += 1

            msg = entry.get("message")
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            content = msg.get("content")

            # --- Check content format ---
            if role == "user":
                if isinstance(content, str):
                    user_content_string_count += 1
                    if user_content_string_example is None:
                        user_content_string_example = {
                            "file": filepath, "line": lineno,
                            "snippet": content[:200]
                        }
                elif isinstance(content, list):
                    user_content_array_count += 1
                    if user_content_array_example is None:
                        block_types = [b.get("type") for b in content if isinstance(b, dict)]
                        user_content_array_example = {
                            "file": filepath, "line": lineno,
                            "block_types": block_types,
                            "num_blocks": len(content)
                        }

            elif role == "assistant":
                if isinstance(content, str):
                    assistant_content_string_count += 1
                    if assistant_content_string_example is None:
                        assistant_content_string_example = {
                            "file": filepath, "line": lineno,
                            "snippet": content[:200]
                        }
                elif isinstance(content, list):
                    assistant_content_array_count += 1

                # --- Check usage fields (point 10) ---
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    if usage_example is None:
                        usage_example = {"file": filepath, "line": lineno, "usage": usage}
                    for k in usage.keys():
                        usage_fields[k] += 1
                    cc = usage.get("cache_creation")
                    if isinstance(cc, dict):
                        for k in cc.keys():
                            usage_cache_creation_fields[k] += 1
                    if "server_tool_use" in usage:
                        has_server_tool_use += 1
                    if "iterations" in usage:
                        has_iterations += 1
                    if "speed" in usage:
                        has_speed += 1

            # --- Scan content blocks ---
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue

                    btype = block.get("type")
                    if btype is None:
                        continue

                    content_block_types[btype] += 1
                    block_type_by_role[role][btype] += 1

                    # Track all fields per block type
                    for k in block.keys():
                        content_block_fields_by_type[btype][k] += 1

                    # 4. Image blocks
                    if btype == "image":
                        image_block_count += 1
                        if image_block_example is None:
                            example_block = dict(block)
                            src = example_block.get("source", {})
                            if isinstance(src, dict) and "data" in src:
                                example_block["source"] = {
                                    **src,
                                    "data": src["data"][:80] + "...[truncated]"
                                }
                            image_block_example = {
                                "file": filepath, "line": lineno,
                                "block": example_block
                            }

                    # 5. Document blocks
                    elif btype == "document":
                        document_block_count += 1
                        if document_block_example is None:
                            example_block = dict(block)
                            src = example_block.get("source", {})
                            if isinstance(src, dict) and "data" in src:
                                example_block["source"] = {
                                    **src,
                                    "data": src["data"][:80] + "...[truncated]"
                                }
                            document_block_example = {
                                "file": filepath, "line": lineno,
                                "block": example_block
                            }

                    # 6. tool_reference blocks
                    elif btype == "tool_reference":
                        tool_reference_count += 1
                        if tool_reference_example is None:
                            tool_reference_example = {
                                "file": filepath, "line": lineno,
                                "block": block
                            }

                    # 7. Unknown block types
                    if btype not in KNOWN_BLOCK_TYPES:
                        if len(unknown_block_types[btype]) < 3:
                            unknown_block_types[btype].append(
                                (filepath, lineno, {k: (str(v)[:100] if isinstance(v, str) else v) for k, v in block.items()})
                            )

                    # 8. Thinking block signature
                    if btype == "thinking":
                        if thinking_example is None:
                            thinking_example = {
                                "file": filepath, "line": lineno,
                                "has_signature": "signature" in block,
                                "fields": list(block.keys())
                            }
                        if "signature" in block:
                            thinking_with_signature += 1
                            sig = block["signature"]
                            # Quick base64 check: only valid base64 chars
                            import re
                            if not re.match(r'^[A-Za-z0-9+/=]+$', str(sig)):
                                thinking_sig_not_base64 += 1
                        else:
                            thinking_without_signature += 1

                    # 9. Text blocks
                    if btype == "text":
                        text_block_total += 1
                        text = block.get("text", "")
                        if isinstance(text, str):
                            # Check for JSON
                            stripped = text.strip()
                            if (stripped.startswith("{") and stripped.endswith("}")) or \
                               (stripped.startswith("[") and stripped.endswith("]")):
                                try:
                                    json.loads(stripped)
                                    text_with_json += 1
                                except json.JSONDecodeError:
                                    pass
                            # Check for markdown tables
                            if "|" in text and "---" in text:
                                text_with_markdown_table += 1

    # =================== REPORT ===================
    print("\n" + "=" * 80)
    print("CONTENT BLOCK AUDIT REPORT")
    print("=" * 80)

    print(f"\nTotal JSONL files scanned: {len(files)}")
    print(f"Total entries parsed: {total_entries}")
    print(f"\nEntry type distribution:")
    for t, c in entry_type_counts.most_common():
        print(f"  {t}: {c}")

    # --- Point 1: All distinct content block types ---
    print("\n" + "-" * 60)
    print("1. ALL DISTINCT CONTENT BLOCK TYPES")
    print("-" * 60)
    for btype, count in content_block_types.most_common():
        print(f"  {btype}: {count}")
    print(f"\n  By role:")
    for role, types in sorted(block_type_by_role.items()):
        print(f"    {role}:")
        for btype, count in types.most_common():
            print(f"      {btype}: {count}")

    print(f"\n  Fields per block type:")
    for btype in sorted(content_block_fields_by_type.keys()):
        fields = content_block_fields_by_type[btype]
        print(f"    {btype}: {dict(fields.most_common())}")

    # --- Point 2: User content string vs array ---
    print("\n" + "-" * 60)
    print("2. USER MESSAGE CONTENT: STRING vs ARRAY")
    print("-" * 60)
    print(f"  String content: {user_content_string_count}")
    print(f"  Array content:  {user_content_array_count}")
    if user_content_string_example:
        print(f"  String example: {user_content_string_example['file']}:{user_content_string_example['line']}")
        print(f"    snippet: {user_content_string_example['snippet'][:120]}")
    if user_content_array_example:
        print(f"  Array example: {user_content_array_example['file']}:{user_content_array_example['line']}")
        print(f"    block_types: {user_content_array_example['block_types']}")

    # --- Point 3: Assistant content string vs array ---
    print("\n" + "-" * 60)
    print("3. ASSISTANT MESSAGE CONTENT: STRING vs ARRAY")
    print("-" * 60)
    print(f"  String content: {assistant_content_string_count}")
    print(f"  Array content:  {assistant_content_array_count}")
    if assistant_content_string_example:
        print(f"  String example: {assistant_content_string_example['file']}:{assistant_content_string_example['line']}")
        print(f"    snippet: {assistant_content_string_example['snippet'][:120]}")
    else:
        print("  No string content found for assistant messages.")

    # --- Point 4: Image blocks ---
    print("\n" + "-" * 60)
    print("4. IMAGE BLOCKS")
    print("-" * 60)
    print(f"  Total image blocks found: {image_block_count}")
    if image_block_example:
        print(f"  Example: {image_block_example['file']}:{image_block_example['line']}")
        print(f"    {json.dumps(image_block_example['block'], indent=4)}")
    else:
        print("  No image blocks found.")

    # --- Point 5: Document blocks ---
    print("\n" + "-" * 60)
    print("5. DOCUMENT BLOCKS")
    print("-" * 60)
    print(f"  Total document blocks found: {document_block_count}")
    if document_block_example:
        print(f"  Example: {document_block_example['file']}:{document_block_example['line']}")
        print(f"    {json.dumps(document_block_example['block'], indent=4)}")
    else:
        print("  No document blocks found.")

    # --- Point 6: tool_reference blocks ---
    print("\n" + "-" * 60)
    print("6. TOOL_REFERENCE BLOCKS")
    print("-" * 60)
    print(f"  Total tool_reference blocks found: {tool_reference_count}")
    if tool_reference_example:
        print(f"  Example: {tool_reference_example['file']}:{tool_reference_example['line']}")
        print(f"    {json.dumps(tool_reference_example['block'], indent=4)[:500]}")
    else:
        print("  No tool_reference blocks found.")

    # --- Point 7: Undocumented block types ---
    print("\n" + "-" * 60)
    print("7. UNDOCUMENTED / UNEXPECTED CONTENT BLOCK TYPES")
    print("-" * 60)
    if unknown_block_types:
        for btype, examples in unknown_block_types.items():
            if btype == "tool_reference":
                continue  # reported above
            print(f"  '{btype}' ({content_block_types[btype]} occurrences):")
            for fp, ln, block_data in examples[:2]:
                # Truncate large values for display
                display = {}
                for k, v in block_data.items():
                    if isinstance(v, str) and len(v) > 100:
                        display[k] = v[:100] + "..."
                    elif isinstance(v, dict):
                        display[k] = "{...}"
                    else:
                        display[k] = v
                print(f"    {fp}:{ln}")
                print(f"      {json.dumps(display, default=str)}")
    else:
        print("  No undocumented block types found.")

    # --- Point 8: Thinking block signatures ---
    print("\n" + "-" * 60)
    print("8. THINKING BLOCK SIGNATURES")
    print("-" * 60)
    print(f"  With signature:    {thinking_with_signature}")
    print(f"  Without signature: {thinking_without_signature}")
    print(f"  Non-base64 sigs:   {thinking_sig_not_base64}")
    if thinking_example:
        print(f"  Example fields: {thinking_example['fields']}")
        print(f"  Example file: {thinking_example['file']}:{thinking_example['line']}")

    # --- Point 9: Text blocks with structured data ---
    print("\n" + "-" * 60)
    print("9. TEXT BLOCKS WITH STRUCTURED DATA")
    print("-" * 60)
    print(f"  Total text blocks:     {text_block_total}")
    print(f"  With valid JSON:       {text_with_json}")
    print(f"  With markdown tables:  {text_with_markdown_table}")

    # --- Point 10: Assistant usage fields ---
    print("\n" + "-" * 60)
    print("10. ASSISTANT MESSAGE USAGE FIELDS")
    print("-" * 60)
    print(f"  All usage fields encountered:")
    for field, count in usage_fields.most_common():
        print(f"    {field}: {count}")
    if usage_cache_creation_fields:
        print(f"  cache_creation sub-fields:")
        for field, count in usage_cache_creation_fields.most_common():
            print(f"    {field}: {count}")
    print(f"  'server_tool_use' present: {has_server_tool_use}")
    print(f"  'iterations' present:      {has_iterations}")
    print(f"  'speed' present:           {has_speed}")
    if usage_example:
        print(f"  Example: {usage_example['file']}:{usage_example['line']}")
        print(f"    {json.dumps(usage_example['usage'], indent=4)}")

    print("\n" + "=" * 80)
    print("AUDIT COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
