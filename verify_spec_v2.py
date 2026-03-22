#!/usr/bin/env python3
"""
Systematic verification of JSONL_SPEC.md: session data (ground truth) + targeted bundle checks.
Reports ONLY real discrepancies.
"""

import re
import json
import subprocess
from pathlib import Path
from collections import defaultdict

BUNDLE = Path("/tmp/claude_js_bundle.js")
SPEC = Path(__file__).parent / "JSONL_SPEC.md"
SESSIONS_DIR = Path.home() / ".config" / "claude" / "projects"

def grep_bundle(pattern, max_count=50):
    """Grep bundle, return matched text only."""
    cmd = ["grep", "-oP", "-m", str(max_count), pattern, str(BUNDLE)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
    except Exception:
        return []

def bundle_contains(literal):
    """Check if the bundle contains a specific string literal."""
    cmd = ["grep", "-c", "-F", literal, str(BUNDLE)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return int(result.stdout.strip()) > 0
    except Exception:
        return False


def scan_all_sessions():
    """Complete scan of all session files — the ground truth."""
    entry_types = defaultdict(int)
    system_subtypes = defaultdict(int)
    progress_data_types = defaultdict(int)
    content_block_types = defaultdict(int)  # role/blocktype
    nested_block_types = defaultdict(int)   # inside tool_result.content arrays
    tool_names = defaultdict(int)
    permission_modes = set()
    levels = set()
    caller_types = set()
    queue_operations = set()
    top_level_keys = defaultdict(set)  # per entry type
    all_keys = set()
    toolUseResult_keys_per_tool = defaultdict(lambda: defaultdict(int))
    is_sidechain_true_count = 0
    has_agent_id_count = 0
    is_error_values = defaultdict(int)
    content_format = defaultdict(int)  # string vs list vs null for user content
    assistant_content_format = defaultdict(int)
    compact_boundary_parent_null = 0
    compact_boundary_parent_nonnull = 0
    compact_summary_count = 0
    compact_summary_followed_by_user = 0
    tool_result_content_types = defaultdict(int)  # string/list/null
    n_files = 0
    n_entries = 0
    n_errors = 0

    files = list(SESSIONS_DIR.rglob("*.jsonl"))
    print(f"Scanning {len(files)} session files...")

    # For tool name resolution: map tool_use_id -> tool_name
    tool_id_to_name = {}
    # Collect tool_use_ids from assistant messages, then match to user messages

    for f in files:
        n_files += 1
        prev_entry = None
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        n_errors += 1
                        continue

                    n_entries += 1
                    t = obj.get("type", "?")
                    entry_types[t] += 1
                    top_level_keys[t].update(obj.keys())
                    all_keys.update(obj.keys())

                    # Check compact_boundary followed by isCompactSummary
                    if prev_entry and prev_entry.get("subtype") == "compact_boundary":
                        if t == "user" and obj.get("isCompactSummary"):
                            compact_summary_followed_by_user += 1

                    if obj.get("isSidechain") is True:
                        is_sidechain_true_count += 1
                    if "agentId" in obj:
                        has_agent_id_count += 1

                    if "subtype" in obj:
                        system_subtypes[obj["subtype"]] += 1

                    if "level" in obj and isinstance(obj["level"], str):
                        levels.add(obj["level"])

                    if "permissionMode" in obj:
                        permission_modes.add(obj["permissionMode"])

                    if "operation" in obj and t == "queue-operation":
                        queue_operations.add(obj["operation"])

                    if obj.get("isCompactSummary"):
                        compact_summary_count += 1

                    if obj.get("subtype") == "compact_boundary":
                        if obj.get("parentUuid") is None:
                            compact_boundary_parent_null += 1
                        else:
                            compact_boundary_parent_nonnull += 1

                    # Progress data type
                    if t == "progress" and isinstance(obj.get("data"), dict):
                        dt = obj["data"].get("type", "?")
                        progress_data_types[dt] += 1

                    # Message content
                    msg = obj.get("message", {})
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        if t == "user":
                            if isinstance(content, str):
                                content_format["string"] += 1
                            elif isinstance(content, list):
                                content_format["list"] += 1
                            elif content is None:
                                content_format["null"] += 1
                        elif t == "assistant":
                            if isinstance(content, list):
                                assistant_content_format["list"] += 1
                            elif isinstance(content, str):
                                assistant_content_format["string"] += 1

                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and "type" in block:
                                    bt = block["type"]
                                    content_block_types[f"{t}/{bt}"] += 1

                                    if bt == "tool_use":
                                        name = block.get("name", "?")
                                        tool_names[name] += 1
                                        tid = block.get("id", "")
                                        if tid:
                                            tool_id_to_name[tid] = name
                                        caller = block.get("caller")
                                        if caller and isinstance(caller, dict):
                                            caller_types.add(caller.get("type", "?"))
                                        elif caller is None:
                                            pass  # absent

                                    if bt == "tool_result":
                                        tc = block.get("content")
                                        if isinstance(tc, str):
                                            tool_result_content_types["string"] += 1
                                        elif isinstance(tc, list):
                                            tool_result_content_types["list"] += 1
                                            for sub in tc:
                                                if isinstance(sub, dict) and "type" in sub:
                                                    nested_block_types[sub["type"]] += 1
                                        elif tc is None:
                                            tool_result_content_types["null"] += 1

                                        ie = block.get("is_error")
                                        if ie is True:
                                            is_error_values["true"] += 1
                                        elif ie is False:
                                            is_error_values["false"] += 1
                                        else:
                                            is_error_values["absent"] += 1

                    # toolUseResult per tool
                    if "toolUseResult" in obj and isinstance(obj["toolUseResult"], dict):
                        tur = obj["toolUseResult"]
                        # Try to find tool name
                        tool_name = "?"
                        src_id = obj.get("sourceToolUseID", "")
                        if src_id and src_id in tool_id_to_name:
                            tool_name = tool_id_to_name[src_id]
                        for k in tur.keys():
                            toolUseResult_keys_per_tool[tool_name][k] += 1

                    prev_entry = obj
        except Exception:
            n_errors += 1

    return {
        "n_files": n_files, "n_entries": n_entries, "n_errors": n_errors,
        "entry_types": dict(entry_types),
        "system_subtypes": dict(system_subtypes),
        "progress_data_types": dict(progress_data_types),
        "content_block_types": dict(content_block_types),
        "nested_block_types": dict(nested_block_types),
        "tool_names": dict(tool_names),
        "permission_modes": sorted(permission_modes),
        "levels": sorted(levels),
        "caller_types": sorted(caller_types),
        "queue_operations": sorted(queue_operations),
        "top_level_keys": {k: sorted(v) for k, v in top_level_keys.items()},
        "all_keys": sorted(all_keys),
        "is_sidechain_true": is_sidechain_true_count,
        "has_agent_id": has_agent_id_count,
        "compact_boundary_parent_null": compact_boundary_parent_null,
        "compact_boundary_parent_nonnull": compact_boundary_parent_nonnull,
        "compact_summary_count": compact_summary_count,
        "compact_summary_followed_by_user": compact_summary_followed_by_user,
        "content_format": dict(content_format),
        "assistant_content_format": dict(assistant_content_format),
        "tool_result_content_types": dict(tool_result_content_types),
        "is_error_values": dict(is_error_values),
        "toolUseResult_keys_per_tool": {k: dict(v) for k, v in toolUseResult_keys_per_tool.items()},
    }


def parse_spec_claims():
    """Extract specific claims from the spec to verify."""
    text = SPEC.read_text()
    claims = {}

    # Entry types from tables
    entry_types = set()
    for m in re.finditer(r'\| `([a-z][-a-z_]+)` \|', text):
        entry_types.add(m.group(1))
    claims["entry_types"] = entry_types

    # System subtypes mentioned
    subtypes = set()
    for m in re.finditer(r'"subtype":\s*"([a-z_]+)"', text):
        subtypes.add(m.group(1))
    for m in re.finditer(r'`([a-z_]+)`.*?subtype|###.*?([a-z_]+)\n', text):
        for g in m.groups():
            if g and "_" in g:
                subtypes.add(g)
    claims["system_subtypes"] = subtypes

    # Specific boolean claims
    claims["isSidechain_can_be_true"] = "true" in text.lower() and "isSidechain" in text
    claims["compact_boundary_parentUuid_null_only"] = "parentUuid: null" in text and "non-null" not in text.split("compact_boundary")[1].split("###")[0] if "compact_boundary" in text else True
    claims["summary_type_extinct"] = "zero instances" in text.lower() or "Zero instances" in text
    claims["assistant_content_always_array"] = "always an array" in text.lower()
    claims["is_error_only_on_errors"] = "only set on errors" in text.lower()

    return claims


def main():
    data = scan_all_sessions()
    claims = parse_spec_claims()

    issues = []
    confirmed = []

    print(f"\n{'='*70}")
    print(f"SESSION DATA: {data['n_files']} files, {data['n_entries']} entries, {data['n_errors']} parse errors")
    print(f"{'='*70}")

    # 1. Entry types
    print(f"\n--- ENTRY TYPES ---")
    session_types = set(data["entry_types"].keys())
    spec_types = claims["entry_types"]
    missing_from_spec = session_types - spec_types
    if missing_from_spec:
        issues.append(f"Entry types in sessions but not spec: {sorted(missing_from_spec)}")
    else:
        confirmed.append("All session entry types are in spec")
    print(f"  Session types ({len(session_types)}): {sorted(session_types)}")
    print(f"  Types in spec but not sessions: {sorted(spec_types - session_types)}")

    # 2. System subtypes
    print(f"\n--- SYSTEM SUBTYPES ---")
    session_subs = set(data["system_subtypes"].keys())
    print(f"  Found ({len(session_subs)}): {sorted(session_subs)}")
    for s, c in sorted(data["system_subtypes"].items(), key=lambda x: -x[1]):
        print(f"    {s}: {c}")

    # 3. Progress data types
    print(f"\n--- PROGRESS DATA TYPES ---")
    for dt, c in sorted(data["progress_data_types"].items(), key=lambda x: -x[1]):
        print(f"    {dt}: {c}")

    # 4. Content block types
    print(f"\n--- CONTENT BLOCK TYPES ---")
    for bt, c in sorted(data["content_block_types"].items(), key=lambda x: -x[1]):
        print(f"    {bt}: {c}")

    # 5. Nested block types (inside tool_result.content arrays)
    print(f"\n--- NESTED BLOCK TYPES (inside tool_result.content) ---")
    for bt, c in sorted(data["nested_block_types"].items(), key=lambda x: -x[1]):
        print(f"    {bt}: {c}")

    # 6. Tool names
    print(f"\n--- TOOL NAMES ({len(data['tool_names'])}) ---")
    for name, c in sorted(data["tool_names"].items(), key=lambda x: -x[1]):
        print(f"    {name}: {c}")

    # 7. Key checks
    print(f"\n--- KEY CLAIMS ---")

    print(f"  isSidechain=true count: {data['is_sidechain_true']}")
    if data["is_sidechain_true"] > 0:
        confirmed.append(f"isSidechain CAN be true ({data['is_sidechain_true']} entries)")

    print(f"  agentId present: {data['has_agent_id']}")

    print(f"  compact_boundary parentUuid=null: {data['compact_boundary_parent_null']}")
    print(f"  compact_boundary parentUuid!=null: {data['compact_boundary_parent_nonnull']}")
    if data["compact_boundary_parent_nonnull"] > 0:
        confirmed.append(f"compact_boundary can have non-null parentUuid ({data['compact_boundary_parent_nonnull']})")

    print(f"  isCompactSummary messages: {data['compact_summary_count']}")
    print(f"  compact_boundary followed by isCompactSummary user: {data['compact_summary_followed_by_user']}")

    print(f"\n  User content format: {data['content_format']}")
    print(f"  Assistant content format: {data['assistant_content_format']}")
    if data["assistant_content_format"].get("string", 0) > 0:
        issues.append(f"Assistant content is sometimes a string! ({data['assistant_content_format']['string']})")
    else:
        confirmed.append("Assistant content is always an array")

    print(f"\n  tool_result.content types: {data['tool_result_content_types']}")
    print(f"  is_error values: {data['is_error_values']}")

    print(f"\n  Permission modes: {data['permission_modes']}")
    print(f"  Levels: {data['levels']}")
    print(f"  Caller types: {data['caller_types']}")
    print(f"  Queue operations: {data['queue_operations']}")

    # 8. Top-level keys
    print(f"\n--- ALL TOP-LEVEL KEYS ({len(data['all_keys'])}) ---")
    print(f"  {data['all_keys']}")

    # 9. toolUseResult keys per tool
    print(f"\n--- TOOLUSERESULT KEYS PER TOOL ---")
    for tool, keys in sorted(data["toolUseResult_keys_per_tool"].items()):
        print(f"  {tool}: {sorted(keys.keys())}")

    # 10. Bundle spot checks
    print(f"\n--- BUNDLE SPOT CHECKS ---")
    checks = [
        ("microcompact_boundary creation", '"microcompact_boundary"'),
        ("summary type handling", '"summary"'),
        ("redacted_thinking", '"redacted_thinking"'),
        ("powershell_progress", '"powershell_progress"'),
        ("skill_progress", '"skill_progress"'),
        ("tool_progress", '"tool_progress"'),
        ("marble-origami-commit", '"marble-origami-commit"'),
        ("ai-title", '"ai-title"'),
        ("attachment type", '"attachment"'),
        ("preserved_segment", '"preservedSegment"'),
        ("En() filter", 'type==="user"'),
        ("sessions-index.json", 'sessions-index'),
        ("auto permission", '"auto"'),
    ]
    for label, literal in checks:
        found = bundle_contains(literal)
        print(f"  {label}: {'FOUND' if found else 'NOT FOUND'} ({literal})")

    # Summary
    print(f"\n{'='*70}")
    print(f"CONFIRMED CLAIMS: {len(confirmed)}")
    for c in confirmed:
        print(f"  [OK] {c}")
    print(f"\nISSUES: {len(issues)}")
    for i in issues:
        print(f"  [!!] {i}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
