use std::collections::HashMap;
use std::fs;
use std::io::{self, Read as _, Write as _};
use std::path::Path;

use crate::{
    libc_tcflush, pad_or_truncate, terminal_size, ALT_SCREEN_OFF, ALT_SCREEN_ON, BG_BLUE, BLUE,
    BOLD, CYAN, DIM, GREEN, HIDE_CURSOR, MAGENTA, RED, RESET, SHOW_CURSOR, WHITE, YELLOW,
};

/// A single JSONL entry with its raw line and parsed metadata.
struct Entry {
    raw: String,
    entry_type: String,
    uuid: Option<String>,
    parent_uuid: Option<String>,
    role: Option<String>,    // user/assistant
    content_preview: String, // first line of text content
    tool_name: Option<String>,
    is_compact_summary: bool,
    subtype: Option<String>,
    timestamp: Option<String>,
    marked_for_delete: bool,
    line_index: usize, // original line number in file
}

/// Represents the context-visible messages (what the model sees).
struct ContextMessage {
    entry_indices: Vec<usize>, // indices into entries vec (multi-line assistant = multiple)
    display: String,           // one-line display text
    role: String,              // user/assistant/system
    _is_tool_call: bool,
    _is_tool_result: bool,
    marked: bool,
}

pub fn run_editor(session_file: &Path) {
    let content = match fs::read_to_string(session_file) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Failed to read {}: {e}", session_file.display());
            return;
        }
    };

    // Parse all entries
    let mut entries: Vec<Entry> = Vec::new();
    for (i, line) in content.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let obj: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };

        let entry_type = obj["type"].as_str().unwrap_or("").to_string();
        let uuid = obj["uuid"].as_str().map(|s| s.to_string());
        let parent_uuid = obj["parentUuid"].as_str().map(|s| s.to_string());
        let subtype = obj["subtype"].as_str().map(|s| s.to_string());
        let timestamp = obj["timestamp"].as_str().map(|s| s.to_string());
        let is_compact_summary = obj["isCompactSummary"].as_bool().unwrap_or(false);

        let msg = &obj["message"];
        let role = msg["role"].as_str().map(|s| s.to_string());

        // Extract content preview
        let mut content_preview = String::new();
        let mut tool_name = None;

        if let Some(content) = msg.get("content") {
            match content {
                serde_json::Value::String(s) => {
                    content_preview = s.lines().next().unwrap_or("").to_string();
                }
                serde_json::Value::Array(arr) => {
                    for block in arr {
                        let bt = block["type"].as_str().unwrap_or("");
                        match bt {
                            "text" => {
                                if content_preview.is_empty() {
                                    content_preview = block["text"]
                                        .as_str()
                                        .unwrap_or("")
                                        .lines()
                                        .next()
                                        .unwrap_or("")
                                        .to_string();
                                }
                            }
                            "thinking" => {
                                if content_preview.is_empty() {
                                    content_preview = "[thinking]".to_string();
                                }
                            }
                            "tool_use" => {
                                let name =
                                    block["name"].as_str().unwrap_or("?").to_string();
                                tool_name = Some(name.clone());
                                content_preview = format!("[{name}]");
                            }
                            "tool_result" => {
                                let tc = &block["content"];
                                let preview = match tc {
                                    serde_json::Value::String(s) => {
                                        let first = s.lines().next().unwrap_or("");
                                        if first.len() > 60 {
                                            format!("{}…", &first[..60])
                                        } else {
                                            first.to_string()
                                        }
                                    }
                                    _ => "[result]".to_string(),
                                };
                                content_preview = preview;
                            }
                            "image" => content_preview = "[image]".to_string(),
                            "document" => content_preview = "[document]".to_string(),
                            _ => {}
                        }
                    }
                }
                _ => {}
            }
        }

        // For system messages, use subtype as preview
        if entry_type == "system" && content_preview.is_empty() {
            if let Some(ref st) = subtype {
                content_preview = format!("[{st}]");
            }
        }

        entries.push(Entry {
            raw: line.to_string(),
            entry_type,
            uuid,
            parent_uuid,
            role,
            content_preview,
            tool_name,
            is_compact_summary,
            subtype,
            timestamp,
            marked_for_delete: false,
            line_index: i,
        });
    }

    // Build context messages: only API-visible types, grouped by message.id for multi-line assistant
    let mut context_msgs: Vec<ContextMessage> = Vec::new();
    let api_types = ["user", "assistant", "system"];

    for (i, entry) in entries.iter().enumerate() {
        if !api_types.contains(&entry.entry_type.as_str()) {
            continue;
        }
        // Skip system subtypes that are just metadata
        if entry.entry_type == "system" {
            match entry.subtype.as_deref() {
                Some("stop_hook_summary") | Some("turn_duration") => continue,
                _ => {}
            }
        }

        let role = entry
            .role
            .clone()
            .unwrap_or_else(|| entry.entry_type.clone());

        let is_tool_call = entry.tool_name.is_some();
        let _is_tool_result = entry.content_preview.starts_with("[result]")
            || (role == "user" && entry.content_preview.is_empty() && entry.entry_type == "user");

        // Check if this is a tool_result user message
        let is_tr = if entry.entry_type == "user" && entry.role.as_deref() == Some("user") {
            // Parse raw to check for tool_result
            let obj: serde_json::Value = serde_json::from_str(&entry.raw).unwrap_or_default();
            if let Some(arr) = obj["message"]["content"].as_array() {
                arr.iter()
                    .any(|b| b["type"].as_str() == Some("tool_result"))
            } else {
                false
            }
        } else {
            false
        };

        let display = if entry.is_compact_summary {
            "[COMPACTION SUMMARY]".to_string()
        } else {
            entry.content_preview.clone()
        };

        let display_role = if is_tr {
            "tool_result".to_string()
        } else if is_tool_call {
            "tool_call".to_string()
        } else {
            role.clone()
        };

        context_msgs.push(ContextMessage {
            entry_indices: vec![i],
            display,
            role: display_role,
            _is_tool_call: is_tool_call,
            _is_tool_result: is_tr,
            marked: false,
        });
    }

    if context_msgs.is_empty() {
        eprintln!("No API-visible messages found in session.");
        return;
    }

    // Run the TUI
    run_editor_tui(session_file, &mut entries, &mut context_msgs);
}

fn run_editor_tui(
    session_file: &Path,
    entries: &mut Vec<Entry>,
    msgs: &mut Vec<ContextMessage>,
) {
    let _raw = match crate::RawMode::enable() {
        Some(r) => r,
        None => {
            eprintln!("Failed to enable raw terminal mode.");
            return;
        }
    };

    // Flush any stale input from the previous TUI
    {
        use std::os::unix::io::AsRawFd;
        let fd = io::stdin().as_raw_fd();
        unsafe { libc_tcflush(fd, 0); } // TCIFLUSH = 0
    }

    let count = msgs.len();
    let mut cursor: usize = 0;
    let mut scroll_offset: usize = 0;
    let mut dirty = false;

    // Use alternate screen buffer for a clean rendering surface (avoids scrollback issues)
    let _ = io::stderr().write_all(format!("{ALT_SCREEN_ON}{HIDE_CURSOR}").as_bytes());
    let _ = io::stderr().flush();

    let leave = || {
        let _ = io::stderr().write_all(format!("{SHOW_CURSOR}{ALT_SCREEN_OFF}").as_bytes());
        let _ = io::stderr().flush();
    };

    loop {
        let (term_width, term_height) = terminal_size();
        let visible_rows = if term_height > 9 { term_height - 8 } else { 10 };

        if cursor < scroll_offset {
            scroll_offset = cursor;
        }
        if cursor >= scroll_offset + visible_rows {
            scroll_offset = cursor - visible_rows + 1;
        }

        let end = (scroll_offset + visible_rows).min(count);

        let mut out = String::with_capacity(8192);
        // Move cursor home (no clear — we overwrite every line, matching the picker approach)
        out.push_str("\x1b[H");

        // Header
        let marked_count = msgs.iter().filter(|m| m.marked).count();
        let status = if dirty {
            format!("{RED}[{marked_count} marked for deletion]{RESET}")
        } else {
            String::new()
        };
        out.push_str(&format!(
            "{BOLD}{CYAN}Context Editor{RESET}  {DIM}({count} msgs, {visible_rows} rows, {term_width}x{term_height}){RESET}  {status}\x1b[K\n"
        ));
        out.push_str("\x1b[K\n");

        // Column headers
        let w_idx = 4;
        let w_role = 13;
        let w_content = if term_width > w_idx + w_role + 10 {
            term_width - w_idx - w_role - 6
        } else {
            40
        };

        out.push_str(&format!(
            "{BOLD}{DIM} {:<w_idx$}  {:<w_role$}  {:<w_content$}{RESET}\x1b[K\n",
            "#", "Type", "Content",
        ));
        let line_width = w_idx + w_role + w_content + 6;
        out.push_str(&format!("{DIM}{}{RESET}\x1b[K\n", "─".repeat(line_width)));

        // Rows
        for i in scroll_offset..end {
            let m = &msgs[i];
            let selected = i == cursor;

            let idx_str = format!("{:>w_idx$}", i + 1);
            let role_plain = pad_or_truncate(&m.role, w_role);
            let content = pad_or_truncate(&m.display, w_content);

            let mark = if m.marked { "DEL" } else { "   " };

            // Colorize the role (applied AFTER padding so ANSI doesn't affect width)
            let role_colored = match m.role.as_str() {
                "user" => format!("{GREEN}{role_plain}{RESET}"),
                "assistant" => format!("{BLUE}{role_plain}{RESET}"),
                "tool_call" => format!("{MAGENTA}{role_plain}{RESET}"),
                "tool_result" => format!("{YELLOW}{role_plain}{RESET}"),
                "system" => format!("{DIM}{role_plain}{RESET}"),
                _ => role_plain.clone(),
            };

            if selected {
                out.push_str(&format!(
                    "{BG_BLUE}{BOLD}{WHITE} {idx_str} {mark} {role_plain} {content}{RESET}\x1b[K\n",
                ));
            } else if m.marked {
                out.push_str(&format!(
                    " {DIM}{idx_str}{RESET} {RED}{mark}{RESET} {role_colored} {DIM}\x1b[9m{content}\x1b[29m{RESET}\x1b[K\n",
                ));
            } else {
                out.push_str(&format!(
                    " {DIM}{idx_str}{RESET} {DIM}{mark}{RESET} {role_colored} {content}\x1b[K\n",
                ));
            }
        }

        for _ in (end - scroll_offset)..visible_rows {
            out.push_str("\x1b[K\n");
        }

        out.push_str(&format!("{DIM}{}{RESET}\x1b[K\n", "─".repeat(line_width)));

        // Footer
        let sel = &msgs[cursor];
        let ts = if !sel.entry_indices.is_empty() {
            entries[sel.entry_indices[0]]
                .timestamp
                .as_deref()
                .unwrap_or("-")
        } else {
            "-"
        };
        out.push_str(&format!(
            "{DIM}{ts}  |  {}/{count}{RESET}\x1b[K\n",
            cursor + 1,
        ));
        out.push_str(&format!(
            "{DIM}j/k: navigate  d: toggle delete  s: save  q: quit (no save){RESET}\x1b[K"
        ));

        let _ = io::stderr().write_all(out.as_bytes());
        let _ = io::stderr().flush();

        match read_editor_key() {
            EditorKey::Quit => {
                if dirty {
                    // Confirm discard
                    let prompt_row = visible_rows + 7;
                    let _ = io::stderr().write_all(
                        format!(
                            "\x1b[{prompt_row};1H\x1b[K{BOLD}{RED}Discard changes? (y/n){RESET} "
                        )
                        .as_bytes(),
                    );
                    let _ = io::stderr().flush();
                    match read_editor_key() {
                        EditorKey::Char(b'y') | EditorKey::Char(b'Y') => {
                            leave();
                            return;
                        }
                        _ => continue,
                    }
                }
                leave();
                return;
            }
            EditorKey::Up => {
                if cursor > 0 {
                    cursor -= 1;
                }
            }
            EditorKey::Down => {
                if cursor + 1 < count {
                    cursor += 1;
                }
            }
            EditorKey::PageUp => cursor = cursor.saturating_sub(visible_rows),
            EditorKey::PageDown => cursor = (cursor + visible_rows).min(count - 1),
            EditorKey::Home => cursor = 0,
            EditorKey::End => cursor = count - 1,
            EditorKey::Delete => {
                // Toggle mark on current message
                let m = &mut msgs[cursor];
                // Don't allow deleting compact summaries — that breaks the session
                if !entries[m.entry_indices[0]].is_compact_summary {
                    m.marked = !m.marked;
                    for &idx in &m.entry_indices {
                        entries[idx].marked_for_delete = m.marked;
                    }
                    dirty = msgs.iter().any(|m| m.marked);
                    // Move down after marking
                    if cursor + 1 < count {
                        cursor += 1;
                    }
                }
            }
            EditorKey::Save => {
                if !dirty {
                    continue;
                }
                // Build set of UUIDs being deleted and their parent mappings
                let mut deleted_uuids: HashMap<String, Option<String>> = HashMap::new();
                for entry in entries.iter() {
                    if entry.marked_for_delete {
                        if let Some(ref uuid) = entry.uuid {
                            deleted_uuids
                                .insert(uuid.clone(), entry.parent_uuid.clone());
                        }
                    }
                }

                // Create backup
                let backup_path = session_file.with_extension("jsonl.bak");
                if let Err(e) = fs::copy(session_file, &backup_path) {
                    let prompt_row = visible_rows + 7;
                    let _ = io::stderr().write_all(
                        format!(
                            "\x1b[{prompt_row};1H\x1b[K{RED}Backup failed: {e}{RESET}"
                        )
                        .as_bytes(),
                    );
                    let _ = io::stderr().flush();
                    let _ = read_editor_key();
                    continue;
                }

                // Rewrite the file
                let mut output_lines: Vec<String> = Vec::new();
                let content = fs::read_to_string(session_file).unwrap_or_default();

                for (i, line) in content.lines().enumerate() {
                    let line = line.trim();
                    if line.is_empty() {
                        continue;
                    }

                    // Check if this line's entry is marked for deletion
                    let is_deleted = entries.iter().any(|e| e.line_index == i && e.marked_for_delete);

                    if is_deleted {
                        continue; // skip this line
                    }

                    // Re-link parentUuid if it points to a deleted entry
                    let mut obj: serde_json::Value = match serde_json::from_str(line) {
                        Ok(v) => v,
                        Err(_) => {
                            output_lines.push(line.to_string());
                            continue;
                        }
                    };

                    if let Some(parent) = obj.get("parentUuid").and_then(|v| v.as_str()) {
                        let parent = parent.to_string();
                        if let Some(grandparent) = resolve_parent(&parent, &deleted_uuids)
                        {
                            obj["parentUuid"] = match grandparent {
                                Some(gp) => serde_json::Value::String(gp),
                                None => serde_json::Value::Null,
                            };
                            output_lines.push(serde_json::to_string(&obj).unwrap());
                            continue;
                        }
                    }

                    output_lines.push(line.to_string());
                }

                // Write output
                let mut out_content = output_lines.join("\n");
                out_content.push('\n');

                match fs::write(session_file, &out_content) {
                    Ok(_) => {
                        leave();
                        let deleted = msgs.iter().filter(|m| m.marked).count();
                        eprintln!(
                            "Saved. {deleted} messages removed. Backup at {}",
                            backup_path.display()
                        );
                        return;
                    }
                    Err(e) => {
                        // Restore from backup
                        let _ = fs::copy(&backup_path, session_file);
                        let prompt_row = visible_rows + 7;
                        let _ = io::stderr().write_all(
                            format!(
                                "\x1b[{prompt_row};1H\x1b[K{RED}Save failed: {e}. Restored from backup.{RESET}"
                            )
                            .as_bytes(),
                        );
                        let _ = io::stderr().flush();
                        let _ = read_editor_key();
                    }
                }
            }
            _ => {}
        }
    }
}

/// Resolve a parentUuid through the deleted chain to find the first non-deleted ancestor.
fn resolve_parent(
    parent: &str,
    deleted: &HashMap<String, Option<String>>,
) -> Option<Option<String>> {
    if !deleted.contains_key(parent) {
        return None; // parent is not deleted, no re-linking needed
    }
    // Walk up the chain
    let mut current = Some(parent.to_string());
    let mut visited = std::collections::HashSet::new();
    loop {
        match current {
            Some(ref uuid) => {
                if visited.contains(uuid) {
                    return Some(None); // cycle, point to null
                }
                visited.insert(uuid.clone());
                if let Some(grandparent) = deleted.get(uuid) {
                    current = grandparent.clone();
                } else {
                    return Some(current); // found a non-deleted ancestor
                }
            }
            None => return Some(None), // chain ends at root
        }
    }
}

enum EditorKey {
    Up,
    Down,
    PageUp,
    PageDown,
    Home,
    End,
    Delete,
    Save,
    Quit,
    Char(u8),
    Other,
}

fn read_editor_key() -> EditorKey {
    let mut buf = [0u8; 1];
    if io::stdin().read_exact(&mut buf).is_err() {
        return EditorKey::Quit;
    }
    match buf[0] {
        b'q' | b'Q' | 3 => EditorKey::Quit,
        b'k' | b'K' => EditorKey::Up,
        b'j' | b'J' => EditorKey::Down,
        b'd' | b'D' | b' ' => EditorKey::Delete, // d, D, or space to toggle
        b's' | b'S' => EditorKey::Save,
        b'g' => EditorKey::Home,
        b'G' => EditorKey::End,
        27 => {
            let mut seq = [0u8; 2];
            if io::stdin().read_exact(&mut seq).is_err() {
                return EditorKey::Quit;
            }
            if seq[0] == b'[' {
                match seq[1] {
                    b'A' => EditorKey::Up,
                    b'B' => EditorKey::Down,
                    b'5' => {
                        let mut t = [0u8; 1];
                        let _ = io::stdin().read_exact(&mut t);
                        EditorKey::PageUp
                    }
                    b'6' => {
                        let mut t = [0u8; 1];
                        let _ = io::stdin().read_exact(&mut t);
                        EditorKey::PageDown
                    }
                    b'H' => EditorKey::Home,
                    b'F' => EditorKey::End,
                    _ => EditorKey::Other,
                }
            } else {
                EditorKey::Quit
            }
        }
        c => EditorKey::Char(c),
    }
}
