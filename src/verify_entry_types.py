#!/usr/bin/env python3
"""Verify all entry types and field coverage against JSONL_SPEC.md."""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECTS_DIR = Path.home() / ".config" / "claude" / "projects"

# --- Spec definitions ---

SPEC_TYPES = {
    "progress", "assistant", "user", "system",
    "file-history-snapshot", "queue-operation",
    "summary", "last-prompt", "custom-title", "agent-name",
}

SPEC_SYSTEM_SUBTYPES = {
    "compact_boundary", "microcompact_boundary", "turn_duration",
    "stop_hook_summary", "api_error", "local_command",
}

SPEC_PROGRESS_SUBTYPES = {
    "hook_progress", "bash_progress", "agent_progress",
    "mcp_progress", "waiting_for_task",
}

# All 55 top-level keys claimed in the spec
SPEC_ALL_KEYS = {
    "agentName", "cause", "compactMetadata", "content", "customTitle", "cwd", "data",
    "durationMs", "entrypoint", "error", "forkedFrom", "gitBranch", "hasOutput",
    "hookCount", "hookErrors", "hookInfos", "isApiErrorMessage", "isCompactSummary",
    "isMeta", "isSidechain", "isSnapshotUpdate", "isVisibleInTranscriptOnly",
    "lastPrompt", "level", "logicalParentUuid", "maxRetries", "mcpMeta", "message",
    "messageId", "microcompactMetadata", "operation", "parentToolUseID", "parentUuid",
    "permissionMode", "planContent", "preventedContinuation", "promptId", "requestId",
    "retryAttempt", "retryInMs", "sessionId", "slug", "snapshot", "sourceToolAssistantUUID",
    "sourceToolUseID", "stopReason", "subtype", "teamName", "thinkingMetadata",
    "timestamp", "todos", "toolUseID", "toolUseResult", "type", "userType", "uuid", "version",
}

# Spec frequency claims
SPEC_FREQUENCIES = {
    "progress": 0.75,
    "assistant": 0.12,
    "user": 0.08,
    "system": 0.02,
    "file-history-snapshot": 0.03,
    "queue-operation": 0.001,  # <1%
}


def scan_all_files():
    type_counts = Counter()
    type_subtype_counts = Counter()
    progress_data_type_counts = Counter()
    keys_by_type = defaultdict(set)
    keys_by_type_subtype = defaultdict(set)
    all_keys_seen = set()
    total_entries = 0

    # Track special cases
    isSidechain_true_examples = []
    summary_examples = []
    last_prompt_examples = []
    custom_title_examples = []
    agent_name_examples = []
    isCompactSummary_examples = []
    forkedFrom_examples = []

    # Track keys per entry type
    keys_per_type_examples = defaultdict(dict)  # {type: {key: (file, line_no, snippet)}}

    files = sorted(PROJECTS_DIR.rglob("*.jsonl"))
    total_files = len(files)
    errors = []

    for fi, fpath in enumerate(files):
        if fi % 200 == 0:
            print(f"  Scanning file {fi+1}/{total_files}...", file=sys.stderr)
        try:
            with open(fpath, "r", errors="replace") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as e:
                        errors.append((str(fpath), line_no, f"JSON parse error: {e}"))
                        continue

                    if not isinstance(entry, dict):
                        continue

                    total_entries += 1
                    entry_type = entry.get("type", "<missing>")
                    type_counts[entry_type] += 1

                    top_keys = set(entry.keys())
                    all_keys_seen.update(top_keys)
                    keys_by_type[entry_type].update(top_keys)

                    # For new keys not yet seen for this type, record example
                    for k in top_keys:
                        if k not in keys_per_type_examples[entry_type]:
                            val = entry[k]
                            if isinstance(val, str) and len(val) > 100:
                                val = val[:100] + "..."
                            elif isinstance(val, (dict, list)):
                                s = json.dumps(val)
                                if len(s) > 100:
                                    val = s[:100] + "..."
                                else:
                                    val = s
                            keys_per_type_examples[entry_type][k] = (str(fpath), line_no, val)

                    # System subtypes
                    subtype = entry.get("subtype")
                    if subtype:
                        type_subtype_counts[(entry_type, subtype)] += 1
                        keys_by_type_subtype[(entry_type, subtype)].update(top_keys)

                    # Progress data.type
                    if entry_type == "progress":
                        data = entry.get("data")
                        if isinstance(data, dict):
                            dt = data.get("type", "<missing>")
                            progress_data_type_counts[dt] += 1

                    # Special case tracking
                    if entry.get("isSidechain") is True and len(isSidechain_true_examples) < 5:
                        isSidechain_true_examples.append((str(fpath), line_no, {k: entry[k] for k in ["type", "uuid", "isSidechain"] if k in entry}))

                    if entry_type == "summary" and len(summary_examples) < 5:
                        summary_examples.append((str(fpath), line_no, list(entry.keys())[:15]))

                    if entry_type == "last-prompt" and len(last_prompt_examples) < 5:
                        last_prompt_examples.append((str(fpath), line_no, list(entry.keys())))

                    if entry_type == "custom-title" and len(custom_title_examples) < 5:
                        custom_title_examples.append((str(fpath), line_no, list(entry.keys())))

                    if entry_type == "agent-name" and len(agent_name_examples) < 5:
                        agent_name_examples.append((str(fpath), line_no, list(entry.keys())))

                    if entry.get("isCompactSummary") and len(isCompactSummary_examples) < 3:
                        isCompactSummary_examples.append((str(fpath), line_no))

                    if entry.get("forkedFrom") and len(forkedFrom_examples) < 3:
                        forkedFrom_examples.append((str(fpath), line_no, entry["forkedFrom"]))

        except Exception as e:
            errors.append((str(fpath), 0, f"File error: {e}"))

    return {
        "total_entries": total_entries,
        "total_files": total_files,
        "type_counts": type_counts,
        "type_subtype_counts": type_subtype_counts,
        "progress_data_type_counts": progress_data_type_counts,
        "keys_by_type": keys_by_type,
        "keys_by_type_subtype": keys_by_type_subtype,
        "all_keys_seen": all_keys_seen,
        "keys_per_type_examples": keys_per_type_examples,
        "isSidechain_true_examples": isSidechain_true_examples,
        "summary_examples": summary_examples,
        "last_prompt_examples": last_prompt_examples,
        "custom_title_examples": custom_title_examples,
        "agent_name_examples": agent_name_examples,
        "isCompactSummary_examples": isCompactSummary_examples,
        "forkedFrom_examples": forkedFrom_examples,
        "errors": errors[:20],
    }


def report(data):
    print("=" * 80)
    print("ENTRY TYPE & FIELD COVERAGE AUDIT")
    print(f"Scanned {data['total_files']} files, {data['total_entries']} entries")
    print("=" * 80)

    # 1. All entry types found
    print("\n## 1. Entry Types Found")
    print(f"{'Type':<30} {'Count':>10} {'Pct':>8}")
    print("-" * 50)
    for t, c in data["type_counts"].most_common():
        pct = c / data["total_entries"] * 100
        in_spec = "OK" if t in SPEC_TYPES else "NOT IN SPEC"
        print(f"  {t:<28} {c:>10} {pct:>7.2f}%  {in_spec}")

    # Types in spec but not found
    found_types = set(data["type_counts"].keys())
    missing_from_data = SPEC_TYPES - found_types
    if missing_from_data:
        print(f"\n  SPEC CLAIMS EXIST BUT NOT FOUND: {missing_from_data}")
    extra_in_data = found_types - SPEC_TYPES
    if extra_in_data:
        print(f"\n  FOUND BUT NOT IN SPEC: {extra_in_data}")

    # 2. Frequency comparison
    print("\n## 2. Frequency Comparison (spec vs actual)")
    print(f"{'Type':<25} {'Spec':>8} {'Actual':>8} {'Delta':>8}")
    print("-" * 55)
    for t, spec_pct in sorted(SPEC_FREQUENCIES.items()):
        actual = data["type_counts"].get(t, 0) / data["total_entries"] * 100
        delta = actual - spec_pct * 100
        flag = " <<<" if abs(delta) > 5 else ""
        print(f"  {t:<23} {spec_pct*100:>7.1f}% {actual:>7.2f}% {delta:>+7.2f}%{flag}")

    # 3. System subtypes
    print("\n## 3. System Subtypes (type, subtype)")
    for (t, st), c in sorted(data["type_subtype_counts"].items(), key=lambda x: -x[1]):
        in_spec = "OK" if (t == "system" and st in SPEC_SYSTEM_SUBTYPES) else "CHECK"
        print(f"  ({t}, {st}): {c}  [{in_spec}]")
    found_sys_subtypes = {st for (t, st) in data["type_subtype_counts"] if t == "system"}
    missing_sys = SPEC_SYSTEM_SUBTYPES - found_sys_subtypes
    if missing_sys:
        print(f"  SPEC SYSTEM SUBTYPES NOT FOUND: {missing_sys}")

    # 4. Progress data.type subtypes
    print("\n## 4. Progress data.type Subtypes")
    for dt, c in data["progress_data_type_counts"].most_common():
        in_spec = "OK" if dt in SPEC_PROGRESS_SUBTYPES else "NOT IN SPEC"
        print(f"  {dt}: {c}  [{in_spec}]")
    found_prog = set(data["progress_data_type_counts"].keys())
    missing_prog = SPEC_PROGRESS_SUBTYPES - found_prog
    if missing_prog:
        print(f"  SPEC PROGRESS SUBTYPES NOT FOUND: {missing_prog}")
    extra_prog = found_prog - SPEC_PROGRESS_SUBTYPES
    if extra_prog:
        print(f"  FOUND BUT NOT IN SPEC: {extra_prog}")

    # 5. Top-level keys comparison
    print("\n## 5. Top-Level Key Inventory")
    print(f"  Spec claims {len(SPEC_ALL_KEYS)} keys")
    print(f"  Found {len(data['all_keys_seen'])} distinct keys in data")
    in_spec_not_data = SPEC_ALL_KEYS - data["all_keys_seen"]
    in_data_not_spec = data["all_keys_seen"] - SPEC_ALL_KEYS
    if in_spec_not_data:
        print(f"\n  IN SPEC BUT NOT IN DATA ({len(in_spec_not_data)}):")
        for k in sorted(in_spec_not_data):
            print(f"    - {k}")
    if in_data_not_spec:
        print(f"\n  IN DATA BUT NOT IN SPEC ({len(in_data_not_spec)}):")
        for k in sorted(in_data_not_spec):
            # Find which types use this key
            types_with_key = [t for t, keys in data["keys_by_type"].items() if k in keys]
            example = data["keys_per_type_examples"].get(types_with_key[0], {}).get(k) if types_with_key else None
            ex_str = ""
            if example:
                ex_str = f"  (file: ...{example[0][-60:]}, line {example[1]}, val={example[2]})"
            print(f"    - {k} [in types: {types_with_key}]{ex_str}")

    # 6. Keys per entry type
    print("\n## 6. Keys by Entry Type")
    for t in sorted(data["keys_by_type"].keys()):
        keys = data["keys_by_type"][t]
        print(f"\n  [{t}] ({data['type_counts'][t]} entries, {len(keys)} distinct keys):")
        for k in sorted(keys):
            print(f"    {k}")

    # 7. Special case checks
    print("\n## 7. Special Case Checks")

    print(f"\n  isSidechain=true examples: {len(data['isSidechain_true_examples'])}")
    for ex in data["isSidechain_true_examples"]:
        print(f"    File: {ex[0]}, Line: {ex[1]}, Entry: {ex[2]}")

    print(f"\n  'summary' type entries: {data['type_counts'].get('summary', 0)}")
    for ex in data["summary_examples"]:
        print(f"    File: {ex[0]}, Line: {ex[1]}, Keys: {ex[2]}")

    print(f"\n  'last-prompt' entries: {data['type_counts'].get('last-prompt', 0)}")
    for ex in data["last_prompt_examples"]:
        print(f"    File: {ex[0]}, Line: {ex[1]}, Keys: {ex[2]}")

    print(f"\n  'custom-title' entries: {data['type_counts'].get('custom-title', 0)}")
    for ex in data["custom_title_examples"]:
        print(f"    File: {ex[0]}, Line: {ex[1]}, Keys: {ex[2]}")

    print(f"\n  'agent-name' entries: {data['type_counts'].get('agent-name', 0)}")
    for ex in data["agent_name_examples"]:
        print(f"    File: {ex[0]}, Line: {ex[1]}, Keys: {ex[2]}")

    print(f"\n  isCompactSummary=true: {len(data['isCompactSummary_examples'])} examples found")
    for ex in data["isCompactSummary_examples"]:
        print(f"    File: {ex[0]}, Line: {ex[1]}")

    print(f"\n  forkedFrom present: {len(data['forkedFrom_examples'])} examples found")
    for ex in data["forkedFrom_examples"]:
        print(f"    File: {ex[0]}, Line: {ex[1]}, Value: {ex[2]}")

    # 8. Parse errors
    if data["errors"]:
        print(f"\n## 8. Parse Errors ({len(data['errors'])} shown)")
        for fpath, line_no, msg in data["errors"]:
            print(f"  {fpath}:{line_no} - {msg}")

    print("\n" + "=" * 80)
    print("AUDIT COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    print("Starting full scan of all JSONL session files...", file=sys.stderr)
    data = scan_all_files()
    report(data)
