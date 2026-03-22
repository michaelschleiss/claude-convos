#!/usr/bin/env python3
"""
Systematic verification of JSONL_SPEC.md against the Claude Code JS bundle.
Extracts all type definitions, field names, and schemas from the decompiled source
and checks every claim in the spec.
"""

import re
import json
import subprocess
from pathlib import Path
from collections import defaultdict

BUNDLE = Path("/tmp/claude_js_bundle.js")
SPEC = Path(__file__).parent / "JSONL_SPEC.md"
SESSIONS_DIR = Path.home() / ".config" / "claude" / "projects"

def grep_bundle(pattern, context_after=0, context_before=0, max_count=500):
    """Grep the bundle for a pattern, return list of (line_no, text) tuples."""
    cmd = ["grep", "-n", "-P"]
    if context_after: cmd += ["-A", str(context_after)]
    if context_before: cmd += ["-B", str(context_before)]
    cmd += ["-m", str(max_count), pattern, str(BUNDLE)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        lines = []
        for line in result.stdout.strip().split("\n"):
            if line and not line.startswith("--"):
                parts = line.split(":", 1) if ":" in line else (line, "")
                if len(parts) == 2:
                    try:
                        lines.append((int(parts[0]), parts[1]))
                    except ValueError:
                        lines.append((0, line))
                else:
                    lines.append((0, line))
        return lines
    except (subprocess.TimeoutExpired, Exception) as e:
        return []

def extract_string_literals_near(pattern, radius=200):
    """Find all quoted string literals within radius chars of a pattern match."""
    lines = grep_bundle(pattern, context_after=3)
    strings = set()
    for _, text in lines:
        # Extract all quoted strings
        for m in re.finditer(r'"([^"]{1,80})"', text):
            strings.add(m.group(1))
    return strings

def scan_sessions_for_types():
    """Scan all session files and collect every (type, subtype) and all top-level keys."""
    types = defaultdict(int)
    subtypes = defaultdict(int)
    all_keys = defaultdict(set)
    progress_types = defaultdict(int)
    content_block_types = defaultdict(int)
    tool_names = defaultdict(int)
    permission_modes = set()
    levels = set()
    caller_types = set()
    operations = set()
    toolUseResult_keys = defaultdict(set)

    files = list(SESSIONS_DIR.rglob("*.jsonl"))
    print(f"Scanning {len(files)} session files...")

    for f in files:
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    t = obj.get("type", "")
                    types[t] += 1
                    all_keys[t].update(obj.keys())

                    if "subtype" in obj:
                        subtypes[f"{t}/{obj['subtype']}"] += 1

                    if "level" in obj:
                        levels.add(obj["level"])

                    if "permissionMode" in obj:
                        permission_modes.add(obj["permissionMode"])

                    if "operation" in obj:
                        operations.add(obj["operation"])

                    if t == "progress" and isinstance(obj.get("data"), dict):
                        dt = obj["data"].get("type", "")
                        progress_types[dt] += 1

                    # Content blocks
                    msg = obj.get("message", {})
                    if isinstance(msg, dict):
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and "type" in block:
                                    bt = block["type"]
                                    content_block_types[f"{t}/{bt}"] += 1

                                    if bt == "tool_use":
                                        tool_names[block.get("name", "")] += 1
                                        caller = block.get("caller")
                                        if caller and isinstance(caller, dict):
                                            caller_types.add(caller.get("type", ""))

                                    # Nested content in tool_result
                                    if bt == "tool_result":
                                        tc = block.get("content")
                                        if isinstance(tc, list):
                                            for sub in tc:
                                                if isinstance(sub, dict) and "type" in sub:
                                                    content_block_types[f"tool_result_nested/{sub['type']}"] += 1

                    # toolUseResult keys per tool
                    if "toolUseResult" in obj and "sourceToolUseID" in obj:
                        tur = obj["toolUseResult"]
                        if isinstance(tur, dict):
                            # Find tool name from content
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "tool_result":
                                        tool_id = block.get("tool_use_id", "")
                                        # Can't reliably map to tool name without cross-referencing
                                        break
                            toolUseResult_keys["_all"].update(tur.keys())
        except Exception:
            continue

    return {
        "types": dict(types),
        "subtypes": dict(subtypes),
        "all_keys": {k: sorted(v) for k, v in all_keys.items()},
        "progress_types": dict(progress_types),
        "content_block_types": dict(content_block_types),
        "tool_names": dict(tool_names),
        "permission_modes": sorted(permission_modes),
        "levels": sorted(levels),
        "caller_types": sorted(caller_types),
        "operations": sorted(operations),
        "toolUseResult_keys": {k: sorted(v) for k, v in toolUseResult_keys.items()},
    }

def extract_from_bundle():
    """Extract all type-related definitions from the JS bundle."""
    print("Extracting from JS bundle...")

    results = {}

    # 1. Entry types - search for type literal assignments
    print("  Entry types...")
    type_literals = set()
    for pattern in [r'type:"[a-z_-]+"', r"type:'[a-z_-]+'", r'\.literal\("[a-z_-]+"\)']:
        for _, text in grep_bundle(pattern):
            for m in re.finditer(r'type:"([a-z_-]+)"', text):
                type_literals.add(m.group(1))
            for m in re.finditer(r"type:'([a-z_-]+)'", text):
                type_literals.add(m.group(1))
            for m in re.finditer(r'\.literal\("([a-z_-]+)"\)', text):
                type_literals.add(m.group(1))
    results["entry_types"] = sorted(type_literals)

    # 2. System subtypes
    print("  System subtypes...")
    subtypes = set()
    for _, text in grep_bundle(r'subtype:"[a-z_]+"'):
        for m in re.finditer(r'subtype:"([a-z_]+)"', text):
            subtypes.add(m.group(1))
    results["system_subtypes"] = sorted(subtypes)

    # 3. Progress data.type values
    print("  Progress data types...")
    progress_types = set()
    for pat in [r'"_progress"', r'"progress".*type:', r'type:"[a-z_]+_progress"',
                r'type:"waiting_for_task"', r'type:"query_update"', r'type:"search_results']:
        for _, text in grep_bundle(pat):
            for m in re.finditer(r'type:"([a-z_]+)"', text):
                if "progress" in m.group(1) or m.group(1) in ("waiting_for_task", "query_update", "search_results_received"):
                    progress_types.add(m.group(1))
    results["progress_data_types"] = sorted(progress_types)

    # 4. Tool names
    print("  Tool names...")
    tool_names = set()
    for _, text in grep_bundle(r'name:"[A-Z][a-zA-Z]+"'):
        for m in re.finditer(r'name:"([A-Z][a-zA-Z]+)"', text):
            name = m.group(1)
            if len(name) > 2 and name not in ("Error", "Buffer", "String", "Object", "Array", "Promise", "Symbol", "Function", "Boolean", "Number", "RegExp", "Date", "Map", "Set"):
                tool_names.add(name)
    results["tool_names"] = sorted(tool_names)

    # 5. Permission modes
    print("  Permission modes...")
    modes = set()
    for _, text in grep_bundle(r'"acceptEdits"|"bypassPermissions"|"dontAsk"|"permissionMode"'):
        for m in re.finditer(r'"(acceptEdits|bypassPermissions|default|dontAsk|plan|auto)"', text):
            modes.add(m.group(1))
    results["permission_modes"] = sorted(modes)

    # 6. Content block types
    print("  Content block types...")
    block_types = set()
    for pat in [r'type:"thinking"', r'type:"tool_use"', r'type:"tool_result"',
                r'type:"text"', r'type:"image"', r'type:"document"',
                r'type:"redacted_thinking"', r'type:"tool_reference"',
                r'type:"attachment"']:
        for _, text in grep_bundle(pat):
            for m in re.finditer(r'type:"([a-z_]+)"', text):
                if m.group(1) in ("thinking", "tool_use", "tool_result", "text", "image",
                                   "document", "redacted_thinking", "tool_reference",
                                   "attachment", "base64"):
                    block_types.add(m.group(1))
    results["content_block_types"] = sorted(block_types)

    # 7. caller types
    print("  Caller types...")
    callers = set()
    for _, text in grep_bundle(r'"direct"|"code_execution"'):
        for m in re.finditer(r'"(direct|code_execution[^"]*)"', text):
            callers.add(m.group(1))
    results["caller_types"] = sorted(callers)

    # 8. Level values
    print("  Level values...")
    level_vals = set()
    for _, text in grep_bundle(r'level:"[a-z]+"'):
        for m in re.finditer(r'level:"([a-z]+)"', text):
            level_vals.add(m.group(1))
    results["level_values"] = sorted(level_vals)

    # 9. En() filter function
    print("  En() message filter...")
    en_types = set()
    for _, text in grep_bundle(r'\.type==="user".*\.type==="assistant"', context_after=2):
        for m in re.finditer(r'\.type==="([a-z]+)"', text):
            en_types.add(m.group(1))
    results["en_filter_types"] = sorted(en_types)

    # 10. Queue operation types
    print("  Queue operations...")
    ops = set()
    for _, text in grep_bundle(r'operation:"[a-z]+"'):
        for m in re.finditer(r'operation:"([a-zA-Z]+)"', text):
            ops.add(m.group(1))
    results["queue_operations"] = sorted(ops)

    # 11. Ephemeral progress types (filtered on load)
    print("  Ephemeral progress types...")
    ephemeral = set()
    for _, text in grep_bundle(r'bash_progress.*powershell_progress|mcp_progress.*bash_progress'):
        for m in re.finditer(r'"([a-z_]+_progress)"', text):
            ephemeral.add(m.group(1))
    results["ephemeral_progress"] = sorted(ephemeral)

    # 12. Metadata marker types (pH_ array)
    print("  Metadata markers...")
    markers = set()
    for _, text in grep_bundle(r'"custom-title".*"tag".*"agent-name"'):
        for m in re.finditer(r'"([a-z_-]+)"', text):
            if m.group(1) not in ("type", "true", "false"):
                markers.add(m.group(1))
    results["metadata_markers"] = sorted(markers)

    return results


def parse_spec():
    """Extract all claims from the spec."""
    text = SPEC.read_text()

    results = {}

    # Entry types from the table
    entry_types = set()
    for m in re.finditer(r'\| `([a-z_-]+)` \|', text):
        entry_types.add(m.group(1))
    results["entry_types"] = sorted(entry_types)

    # System subtypes
    subtypes = set()
    for m in re.finditer(r'`([a-z_]+)`.*subtype|subtype.*`([a-z_]+)`', text):
        s = m.group(1) or m.group(2)
        if s:
            subtypes.add(s)
    # Also from subtype:"xxx" in json blocks
    for m in re.finditer(r'"subtype":\s*"([a-z_]+)"', text):
        subtypes.add(m.group(1))
    results["system_subtypes"] = sorted(subtypes)

    # Progress data types
    progress = set()
    for m in re.finditer(r'`([a-z_]+)`', text):
        s = m.group(1)
        if s and ("progress" in s or s in ("waiting_for_task", "query_update", "search_results_received", "skill_progress")):
            progress.add(s)
    results["progress_data_types"] = sorted(progress)

    # Tool names from the table
    tools = set()
    for m in re.finditer(r'\*\*([A-Z][a-zA-Z]+)\*\*', text):
        tools.add(m.group(1))
    results["tool_names"] = sorted(tools)

    # Permission modes
    modes = set()
    for m in re.finditer(r'"(acceptEdits|bypassPermissions|default|dontAsk|plan|auto)"', text):
        modes.add(m.group(1))
    results["permission_modes"] = sorted(modes)

    # Content block types
    blocks = set()
    for m in re.finditer(r'`(thinking|text|tool_use|tool_result|image|document|redacted_thinking|tool_reference)`', text):
        blocks.add(m.group(1))
    results["content_block_types"] = sorted(blocks)

    # Top-level keys
    keys_section = re.search(r'All Top-Level Keys.*?```\n(.*?)```', text, re.DOTALL)
    if keys_section:
        keys = set()
        for m in re.finditer(r'([a-zA-Z]+)', keys_section.group(1)):
            keys.add(m.group(1))
        results["top_level_keys"] = sorted(keys)

    return results


def diff_sets(label, source_label, source, spec_label, spec):
    """Compare two sets and report differences."""
    issues = []
    in_source_not_spec = source - spec
    in_spec_not_source = spec - source

    if in_source_not_spec:
        issues.append(f"  IN {source_label} BUT NOT {spec_label}: {sorted(in_source_not_spec)}")
    if in_spec_not_source:
        issues.append(f"  IN {spec_label} BUT NOT {source_label}: {sorted(in_spec_not_source)}")
    if not issues:
        issues.append(f"  MATCH ({len(source)} items)")

    print(f"\n{'='*60}")
    print(f"CHECK: {label}")
    print(f"{'='*60}")
    for i in issues:
        print(i)
    return len(in_source_not_spec) + len(in_spec_not_source)


def main():
    total_issues = 0

    # Phase 1: Extract from bundle
    bundle_data = extract_from_bundle()

    # Phase 2: Extract from spec
    spec_data = parse_spec()

    # Phase 3: Scan session files
    session_data = scan_sessions_for_types()

    print("\n" + "="*60)
    print("VERIFICATION RESULTS")
    print("="*60)

    # Compare entry types
    total_issues += diff_sets(
        "Entry Types",
        "BUNDLE", set(bundle_data["entry_types"]),
        "SPEC", set(spec_data["entry_types"])
    )

    # Add session data
    session_types = set(session_data["types"].keys())
    total_issues += diff_sets(
        "Entry Types (sessions vs spec)",
        "SESSIONS", session_types,
        "SPEC", set(spec_data["entry_types"])
    )

    # System subtypes
    total_issues += diff_sets(
        "System Subtypes",
        "BUNDLE", set(bundle_data["system_subtypes"]),
        "SPEC", set(spec_data["system_subtypes"])
    )

    session_subtypes = set()
    for k in session_data["subtypes"]:
        parts = k.split("/", 1)
        if len(parts) == 2:
            session_subtypes.add(parts[1])
    total_issues += diff_sets(
        "System Subtypes (sessions vs spec)",
        "SESSIONS", session_subtypes,
        "SPEC", set(spec_data["system_subtypes"])
    )

    # Progress data types
    total_issues += diff_sets(
        "Progress Data Types",
        "BUNDLE", set(bundle_data["progress_data_types"]),
        "SPEC", set(spec_data["progress_data_types"])
    )

    session_progress = set(session_data["progress_types"].keys())
    total_issues += diff_sets(
        "Progress Data Types (sessions vs spec)",
        "SESSIONS", session_progress,
        "SPEC", set(spec_data["progress_data_types"])
    )

    # Tool names
    total_issues += diff_sets(
        "Tool Names",
        "BUNDLE", set(bundle_data["tool_names"]),
        "SPEC", set(spec_data["tool_names"])
    )

    session_tools = set(session_data["tool_names"].keys())
    total_issues += diff_sets(
        "Tool Names (sessions vs spec)",
        "SESSIONS", session_tools,
        "SPEC", set(spec_data["tool_names"])
    )

    # Permission modes
    total_issues += diff_sets(
        "Permission Modes",
        "BUNDLE", set(bundle_data["permission_modes"]),
        "SPEC", set(spec_data["permission_modes"])
    )

    # Content block types
    total_issues += diff_sets(
        "Content Block Types",
        "BUNDLE", set(bundle_data["content_block_types"]) - {"base64"},
        "SPEC", set(spec_data["content_block_types"])
    )

    # Caller types
    total_issues += diff_sets(
        "Caller Types",
        "BUNDLE", set(bundle_data["caller_types"]),
        "SPEC (mentioned)", {"direct", "code_execution", "code_execution_20260120", "code_execution_tool_result"}
    )

    # En() filter
    print(f"\n{'='*60}")
    print("CHECK: En() Message Filter Types")
    print(f"{'='*60}")
    print(f"  BUNDLE: {bundle_data['en_filter_types']}")
    print(f"  SPEC mentions: user, assistant, attachment, system, progress")

    # Queue operations
    total_issues += diff_sets(
        "Queue Operations",
        "BUNDLE", set(bundle_data["queue_operations"]),
        "SPEC", {"enqueue", "dequeue", "remove", "popAll"}
    )

    # Ephemeral progress types
    print(f"\n{'='*60}")
    print("CHECK: Ephemeral Progress Types (filtered on load)")
    print(f"{'='*60}")
    print(f"  BUNDLE: {bundle_data['ephemeral_progress']}")
    print(f"  SPEC: bash_progress, powershell_progress, mcp_progress")

    # Level values
    total_issues += diff_sets(
        "System Message Level Values",
        "BUNDLE", set(bundle_data["level_values"]),
        "SPEC", {"error", "warn", "warning", "info", "debug", "suggestion", "high", "medium", "low"}
    )

    # Session-only: all top-level keys
    session_all_keys = set()
    for keys in session_data["all_keys"].values():
        session_all_keys.update(keys)
    if "top_level_keys" in spec_data:
        total_issues += diff_sets(
            "Top-Level Keys",
            "SESSIONS", session_all_keys,
            "SPEC", set(spec_data["top_level_keys"])
        )

    # Summary
    print(f"\n{'='*60}")
    print(f"TOTAL DISCREPANCIES: {total_issues}")
    print(f"{'='*60}")

    # Detailed session stats
    print(f"\nSession files scanned: {len(list(SESSIONS_DIR.rglob('*.jsonl')))}")
    print(f"Entry types found: {len(session_data['types'])}")
    print(f"Top 10 types: {sorted(session_data['types'].items(), key=lambda x: -x[1])[:10]}")
    print(f"Tool names found: {len(session_data['tool_names'])}")
    print(f"Permission modes: {session_data['permission_modes']}")
    print(f"Levels: {session_data['levels']}")
    print(f"Caller types: {session_data['caller_types']}")
    print(f"Queue operations: {session_data['operations']}")


if __name__ == "__main__":
    main()
