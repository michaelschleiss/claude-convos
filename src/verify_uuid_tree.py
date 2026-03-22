#!/usr/bin/env python3
"""Verify UUID tree structure claims from JSONL_SPEC.md against real session files."""

import json
import sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime

# Top 5 largest session files
FILES = [
    Path("/home/mschleiss/.config/claude/projects/-home-mschleiss-skd-tracking-and-guidance-on-ros/331f5eda-792d-4e67-9060-a0963e2febeb.jsonl"),
    Path("/home/mschleiss/.config/claude/projects/-home-mschleiss-skd-tracking-and-guidance-on-ros/81fd47de-d3c3-4552-8439-9a2de76f8785.jsonl"),
    Path("/home/mschleiss/.config/claude/projects/-home-mschleiss-skd-tracking-and-guidance-on-ros/07879ea5-9c48-4b47-b1a9-97d090aa85ad.jsonl"),
    Path("/home/mschleiss/.config/claude/projects/-home-mschleiss-skd-tracking-and-guidance-on-ros/8ee9668e-db29-4694-8e90-3f482691ae7d.jsonl"),
    Path("/home/mschleiss/.config/claude/projects/-home-mschleiss-skd-tracking-and-guidance-on-ros/ce753a3e-928e-4d6a-8ec1-da82159df531.jsonl"),
]


def parse_jsonl(path):
    """Parse a JSONL file, returning list of (line_number, entry) tuples."""
    entries = []
    with open(path, "r") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append((i, json.loads(line)))
            except json.JSONDecodeError as e:
                print(f"  WARNING: JSON parse error at line {i}: {e}")
    return entries


def analyze_file(path):
    """Run all UUID tree structure checks on a single file."""
    print(f"\n{'='*80}")
    print(f"FILE: {path.name}")
    print(f"SIZE: {path.stat().st_size / 1e6:.1f} MB")
    print(f"{'='*80}")

    entries = parse_jsonl(path)
    print(f"Total JSONL lines: {len(entries)}")

    # Collect all UUIDs and parent relationships
    uuid_entries = {}        # uuid -> entry
    children = defaultdict(list)  # parentUuid -> [child uuids]
    roots = []               # entries with parentUuid=null/missing
    all_uuids = set()
    uuid_type_map = {}       # uuid -> type string

    # Track entries with UUIDs
    uuid_count = 0
    no_uuid_count = 0

    for line_no, entry in entries:
        etype = entry.get("type", "unknown")
        uuid = entry.get("uuid")

        if uuid:
            uuid_count += 1
            all_uuids.add(uuid)
            uuid_entries[uuid] = entry
            uuid_type_map[uuid] = etype

            parent = entry.get("parentUuid")
            if parent is None:
                roots.append(uuid)
            else:
                children[parent].append(uuid)
        else:
            no_uuid_count += 1

    print(f"Entries with UUID: {uuid_count}")
    print(f"Entries without UUID: {no_uuid_count}")
    print(f"Root nodes (parentUuid=null): {len(roots)}")

    # ===== CHECK 1: "Messages form a long linear chain" =====
    print(f"\n--- CHECK 1: Linear chain structure ---")
    # Count branch points (nodes with >1 child)
    branch_points = {p: kids for p, kids in children.items() if len(kids) > 1}
    max_children = max((len(kids) for kids in children.values()), default=0)
    nodes_with_1_child = sum(1 for kids in children.values() if len(kids) == 1)
    leaf_nodes = sum(1 for uuid in all_uuids if uuid not in children or len(children[uuid]) == 0)

    print(f"  Nodes with exactly 1 child: {nodes_with_1_child}")
    print(f"  Branch points (>1 child): {len(branch_points)}")
    print(f"  Leaf nodes (0 children): {leaf_nodes}")
    print(f"  Max children on any node: {max_children}")

    if uuid_count > 0:
        linearity = nodes_with_1_child / uuid_count * 100
        print(f"  Linearity ratio: {linearity:.1f}% of UUID nodes have exactly 1 child")

    # Compute chain depth iteratively (chains can be 15k+ deep)
    def chain_depth(start_uuid):
        """BFS to find max depth from a root node."""
        from collections import deque
        visited = set()
        queue = deque([(start_uuid, 1)])
        max_d = 0
        while queue:
            uid, d = queue.popleft()
            if uid in visited:
                continue
            visited.add(uid)
            max_d = max(max_d, d)
            for kid in children.get(uid, []):
                if kid not in visited:
                    queue.append((kid, d + 1))
        return max_d

    if roots:
        depths = [chain_depth(r) for r in roots[:5]]  # limit to first 5 roots
        print(f"  Max chain depth (from first 5 roots): {max(depths)}")

    # ===== CHECK 2: Branch point classification =====
    print(f"\n--- CHECK 2: Branch point classification ---")
    # Classify what types of children branch points have
    branch_categories = defaultdict(int)
    branch_details = []

    for parent_uuid, kid_uuids in branch_points.items():
        parent_type = uuid_type_map.get(parent_uuid, "unknown")
        child_types = sorted([uuid_type_map.get(k, "unknown") for k in kid_uuids])
        child_types_str = "+".join(child_types)
        category = f"{parent_type} -> ({child_types_str})"
        branch_categories[category] += 1
        if len(branch_details) < 5:
            branch_details.append((parent_uuid, parent_type, child_types))

    total_branches = len(branch_points)
    if total_branches > 0:
        # Categorize per spec claims
        assistant_to_progress_user = 0
        assistant_to_assistant_user = 0
        other = 0

        for parent_uuid, kid_uuids in branch_points.items():
            parent_type = uuid_type_map.get(parent_uuid, "unknown")
            child_types = set(uuid_type_map.get(k, "unknown") for k in kid_uuids)

            if parent_type == "assistant" and "progress" in child_types and "user" in child_types:
                assistant_to_progress_user += 1
            elif parent_type == "assistant" and "assistant" in child_types and "user" in child_types:
                assistant_to_assistant_user += 1
            elif parent_type == "assistant" and "assistant" in child_types:
                assistant_to_assistant_user += 1
            else:
                other += 1

        print(f"  Total branch points: {total_branches}")
        print(f"  assistant -> (progress+user):    {assistant_to_progress_user} ({assistant_to_progress_user/total_branches*100:.1f}%)")
        print(f"  assistant -> (assistant+...):     {assistant_to_assistant_user} ({assistant_to_assistant_user/total_branches*100:.1f}%)")
        print(f"  other:                           {other} ({other/total_branches*100:.1f}%)")

        print(f"\n  All branch categories (parent_type -> child_types):")
        for cat, count in sorted(branch_categories.items(), key=lambda x: -x[1]):
            pct = count / total_branches * 100
            print(f"    {cat}: {count} ({pct:.1f}%)")
    else:
        print(f"  No branch points found (perfectly linear!)")

    # ===== CHECK 3: compact_boundary has parentUuid=null =====
    print(f"\n--- CHECK 3: compact_boundary creates new root ---")
    compact_boundaries = [(ln, e) for ln, e in entries if e.get("type") == "system" and e.get("subtype") == "compact_boundary"]
    compact_ok = 0
    compact_bad = 0
    for ln, cb in compact_boundaries:
        if cb.get("parentUuid") is None:
            compact_ok += 1
        else:
            compact_bad += 1
            print(f"  VIOLATION at line {ln}: compact_boundary has parentUuid={cb.get('parentUuid')}")

    print(f"  Total compact_boundary entries: {len(compact_boundaries)}")
    print(f"  With parentUuid=null: {compact_ok}")
    print(f"  With parentUuid!=null: {compact_bad}")
    print(f"  Root count matches: expected {len(compact_boundaries)+1} roots (1 original + {len(compact_boundaries)} compactions), found {len(roots)} roots")

    # ===== CHECK 4: logicalParentUuid points to a real UUID =====
    print(f"\n--- CHECK 4: logicalParentUuid validity ---")
    logical_ok = 0
    logical_bad = 0
    logical_missing = 0
    for ln, cb in compact_boundaries:
        lpu = cb.get("logicalParentUuid")
        if lpu is None:
            logical_missing += 1
            print(f"  WARNING at line {ln}: compact_boundary missing logicalParentUuid")
        elif lpu in all_uuids:
            logical_ok += 1
        else:
            logical_bad += 1
            print(f"  WARNING at line {ln}: logicalParentUuid={lpu} NOT found in session UUIDs")

    print(f"  logicalParentUuid present & valid: {logical_ok}")
    print(f"  logicalParentUuid present but invalid: {logical_bad}")
    print(f"  logicalParentUuid missing: {logical_missing}")

    # Also check if compact_boundary is followed by isCompactSummary=true user message
    print(f"\n  Checking compact_boundary -> isCompactSummary sequence:")
    for ln, cb in compact_boundaries:
        cb_uuid = cb.get("uuid")
        # Find children of this compact_boundary
        cb_children = children.get(cb_uuid, [])
        summary_children = [c for c in cb_children if uuid_entries.get(c, {}).get("isCompactSummary") == True]
        if summary_children:
            print(f"    Line {ln}: compact_boundary -> isCompactSummary child(ren): OK")
        else:
            child_types = [uuid_type_map.get(c, "?") for c in cb_children]
            print(f"    Line {ln}: compact_boundary -> children types: {child_types} (NO isCompactSummary found)")

    # ===== CHECK 5: Forked sessions =====
    print(f"\n--- CHECK 5: Forked session detection ---")
    forked_entries = [(ln, e) for ln, e in entries if e.get("forkedFrom") is not None]
    print(f"  Entries with forkedFrom: {len(forked_entries)}")
    if forked_entries:
        # Check if forkedFrom.messageUuid == entry's own uuid
        match_count = 0
        mismatch_count = 0
        for ln, e in forked_entries:
            fk = e.get("forkedFrom", {})
            if fk.get("messageUuid") == e.get("uuid"):
                match_count += 1
            else:
                mismatch_count += 1
                if mismatch_count <= 3:
                    print(f"  MISMATCH at line {ln}: uuid={e.get('uuid')} forkedFrom.messageUuid={fk.get('messageUuid')}")
        print(f"  forkedFrom.messageUuid == own uuid: {match_count}")
        print(f"  forkedFrom.messageUuid != own uuid: {mismatch_count}")
    else:
        print(f"  (This file is not a forked session)")

    # ===== CHECK 6: Tool call cycle sequence =====
    print(f"\n--- CHECK 6: Tool call cycle sequence ---")
    # Find assistant tool_use entries and verify the sequence
    tool_use_entries = []
    for ln, e in entries:
        if e.get("type") == "assistant":
            msg = e.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_use_entries.append((ln, e, block.get("id")))

    print(f"  Total assistant tool_use entries: {len(tool_use_entries)}")

    # For each tool_use, check what follows it in the UUID chain
    cycle_correct = 0
    cycle_incorrect = 0
    cycle_examples = []

    for ln, e, tool_id in tool_use_entries[:200]:  # sample first 200
        uuid = e.get("uuid")
        if not uuid:
            continue
        # Get children
        kids = children.get(uuid, [])
        kid_types = [uuid_type_map.get(k, "?") for k in kids]

        # Expected: children should include progress and/or user entries
        has_progress = "progress" in kid_types
        has_user = "user" in kid_types
        has_assistant = "assistant" in kid_types

        if has_user or has_progress:
            cycle_correct += 1
        else:
            cycle_incorrect += 1
            if len(cycle_examples) < 3:
                cycle_examples.append(f"line {ln}: uuid={uuid}, children types={kid_types}")

    print(f"  Tool uses with expected children (progress/user): {cycle_correct}")
    print(f"  Tool uses with unexpected children: {cycle_incorrect}")
    for ex in cycle_examples:
        print(f"    Example: {ex}")

    # ===== CHECK 7: Chronological ordering =====
    print(f"\n--- CHECK 7: Chronological ordering ---")
    timestamps = []
    for ln, e in entries:
        ts = e.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                timestamps.append((ln, dt, e.get("type", "?")))
            except (ValueError, TypeError):
                pass

    out_of_order = 0
    max_backwards_ms = 0
    oo_examples = []
    for i in range(1, len(timestamps)):
        prev_ln, prev_dt, prev_type = timestamps[i-1]
        curr_ln, curr_dt, curr_type = timestamps[i]
        if curr_dt < prev_dt:
            out_of_order += 1
            diff_ms = (prev_dt - curr_dt).total_seconds() * 1000
            max_backwards_ms = max(max_backwards_ms, diff_ms)
            if len(oo_examples) < 5:
                oo_examples.append(
                    f"  lines {prev_ln}->{curr_ln}: {prev_type}({prev_dt.isoformat()}) > {curr_type}({curr_dt.isoformat()}) by {diff_ms:.0f}ms"
                )

    print(f"  Total timestamped entries: {len(timestamps)}")
    print(f"  Out-of-order pairs: {out_of_order}")
    if out_of_order:
        print(f"  Max backwards jump: {max_backwards_ms:.0f}ms")
        for ex in oo_examples:
            print(ex)
    else:
        print(f"  Strictly chronological: YES")

    # ===== CHECK 8: Parallel tool calls share message.id =====
    print(f"\n--- CHECK 8: Parallel tool calls share message.id ---")
    # Group assistant entries by message.id
    msg_id_groups = defaultdict(list)
    for ln, e in entries:
        if e.get("type") == "assistant":
            msg = e.get("message", {})
            mid = msg.get("id")
            if mid:
                msg_id_groups[mid].append((ln, e))

    multi_line_msgs = {mid: es for mid, es in msg_id_groups.items() if len(es) > 1}
    print(f"  Unique message.ids: {len(msg_id_groups)}")
    print(f"  message.ids spanning multiple lines: {len(multi_line_msgs)}")

    # Check that multi-line messages form a chain via parentUuid
    chain_ok = 0
    chain_bad = 0
    for mid, es in list(multi_line_msgs.items())[:50]:
        uuids_in_group = [e.get("uuid") for _, e in es]
        # Check each entry's parentUuid points to the previous in the group
        for i in range(1, len(es)):
            curr_uuid = es[i][1].get("uuid")
            curr_parent = es[i][1].get("parentUuid")
            prev_uuid = es[i-1][1].get("uuid")
            if curr_parent == prev_uuid:
                chain_ok += 1
            else:
                chain_bad += 1

    if multi_line_msgs:
        total_checked = chain_ok + chain_bad
        print(f"  Multi-line msg parent chain correct: {chain_ok}/{total_checked}")
        if chain_bad:
            print(f"  Chain violations: {chain_bad}")

    # Examine content block types in multi-line messages
    print(f"\n  Content block patterns in multi-line messages (sample up to 20):")
    pattern_counts = defaultdict(int)
    for mid, es in list(multi_line_msgs.items())[:100]:
        block_types = []
        for _, e in es:
            content = e.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_types.append(block.get("type", "?"))
        pattern = " -> ".join(block_types)
        pattern_counts[pattern] += 1

    for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"    [{count}x] {pattern}")

    # ===== CHECK: Orphaned UUIDs =====
    print(f"\n--- BONUS: Orphaned UUID check ---")
    orphaned = 0
    for uuid in all_uuids:
        entry = uuid_entries[uuid]
        parent = entry.get("parentUuid")
        if parent is not None and parent not in all_uuids:
            orphaned += 1
            if orphaned <= 3:
                print(f"  Orphan: uuid={uuid} references missing parentUuid={parent}")
    print(f"  Total orphaned references: {orphaned}")

    return {
        "file": path.name,
        "total_lines": len(entries),
        "uuid_entries": uuid_count,
        "roots": len(roots),
        "branch_points": len(branch_points),
        "compact_boundaries": len(compact_boundaries),
        "compact_bad": compact_bad,
        "logical_ok": logical_ok,
        "logical_bad": logical_bad,
        "forked_entries": len(forked_entries),
        "out_of_order": out_of_order,
        "multi_line_msgs": len(multi_line_msgs),
        "orphaned": orphaned,
    }


def main():
    print("UUID Tree Structure Verification")
    print("=" * 80)

    results = []
    for f in FILES:
        if not f.exists():
            print(f"\nSKIPPING (not found): {f}")
            continue
        results.append(analyze_file(f))

    # Summary
    print(f"\n\n{'='*80}")
    print("AGGREGATE SUMMARY")
    print(f"{'='*80}")
    print(f"{'File':<42} {'Lines':>7} {'UUIDs':>7} {'Roots':>6} {'Branch':>7} {'Compact':>8} {'OOO':>5} {'Orphan':>7}")
    print("-" * 95)
    for r in results:
        print(f"{r['file']:<42} {r['total_lines']:>7} {r['uuid_entries']:>7} {r['roots']:>6} {r['branch_points']:>7} {r['compact_boundaries']:>8} {r['out_of_order']:>5} {r['orphaned']:>7}")

    total_branches = sum(r["branch_points"] for r in results)
    total_compact_bad = sum(r["compact_bad"] for r in results)
    total_logical_bad = sum(r["logical_bad"] for r in results)
    total_orphaned = sum(r["orphaned"] for r in results)

    print(f"\nKey findings:")
    print(f"  Total branch points across all files: {total_branches}")
    print(f"  compact_boundary violations (parentUuid!=null): {total_compact_bad}")
    print(f"  Invalid logicalParentUuid references: {total_logical_bad}")
    print(f"  Total orphaned UUID references: {total_orphaned}")


if __name__ == "__main__":
    main()
