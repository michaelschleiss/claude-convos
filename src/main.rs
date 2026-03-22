mod editor;

use chrono::{DateTime, Local, Utc};
use clap::Parser;
use rayon::prelude::*;
use serde::Deserialize;
use std::fs;
use std::io::{self, BufRead, BufReader, Read as _, Write as _};
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;

const RESET: &str = "\x1b[0m";
const BOLD: &str = "\x1b[1m";
const DIM: &str = "\x1b[2m";
const CYAN: &str = "\x1b[36m";
const YELLOW: &str = "\x1b[33m";
const GREEN: &str = "\x1b[32m";
const MAGENTA: &str = "\x1b[35m";
const WHITE: &str = "\x1b[37m";
const BLUE: &str = "\x1b[34m";
const RED: &str = "\x1b[31m";
const BG_BLUE: &str = "\x1b[44m";
const HIDE_CURSOR: &str = "\x1b[?25l";
const SHOW_CURSOR: &str = "\x1b[?25h";

#[derive(Parser)]
#[command(
    name = "claude-conversations",
    about = "Browse all Claude Code conversations across all projects"
)]
struct Cli {
    /// Filter conversations by search term (matches summary, message, path, model)
    #[arg(short, long)]
    search: Option<String>,

    /// Limit to N most recent conversations (default: all)
    #[arg(short, long)]
    num: Option<usize>,

    /// Show agent/subagent sessions too
    #[arg(short, long)]
    agents: bool,

    /// Sort by: date (default), project, model
    #[arg(long, default_value = "date")]
    sort: String,

    /// Output as JSON instead of interactive display
    #[arg(long)]
    json: bool,
}

#[derive(Deserialize)]
struct MessageContent {
    role: Option<String>,
    content: Option<serde_json::Value>,
    model: Option<String>,
}

#[derive(Deserialize)]
struct SessionLine {
    #[serde(rename = "type")]
    line_type: Option<String>,
    summary: Option<String>,
    message: Option<MessageContent>,
    timestamp: Option<String>,
    cwd: Option<String>,
    #[serde(rename = "sessionId")]
    session_id: Option<String>,
    #[serde(rename = "agentId")]
    agent_id: Option<String>,
    version: Option<String>,
}

#[derive(Clone, serde::Serialize)]
struct ConversationInfo {
    session_id: String,
    summary: String,
    first_message: String,
    timestamp: Option<DateTime<Utc>>,
    cwd: String,
    model: String,
    version: String,
    message_count: usize,
    is_agent: bool,
    project_dir: String,
    #[serde(skip)]
    file_path: PathBuf,
}

fn extract_text_content(content: &serde_json::Value) -> String {
    match content {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Array(arr) => {
            for item in arr {
                if let Some(obj) = item.as_object() {
                    if obj.get("type").and_then(|v| v.as_str()) == Some("text") {
                        if let Some(text) = obj.get("text").and_then(|v| v.as_str()) {
                            return text.to_string();
                        }
                    }
                }
            }
            String::new()
        }
        _ => String::new(),
    }
}

fn parse_session(path: &PathBuf, project_dir: &str) -> Option<ConversationInfo> {
    let file = fs::File::open(path).ok()?;
    let reader = BufReader::new(file);

    let mut summary = String::new();
    let mut first_message = String::new();
    let mut first_timestamp: Option<DateTime<Utc>> = None;
    let mut cwd = String::new();
    let mut session_id = String::new();
    let mut model = String::new();
    let mut version = String::new();
    let mut is_agent = false;
    let mut message_count: usize = 0;

    for line in reader.lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue,
        };
        if line.trim().is_empty() {
            continue;
        }

        let entry: SessionLine = match serde_json::from_str(&line) {
            Ok(e) => e,
            Err(_) => continue,
        };

        if let Some(ref s) = entry.summary {
            if entry.line_type.as_deref() == Some("summary") && summary.is_empty() {
                summary = s.clone();
            }
        }

        if let Some(ref aid) = entry.agent_id {
            if !aid.is_empty() {
                is_agent = true;
            }
        }

        if let Some(ref msg) = entry.message {
            if msg.role.as_deref() == Some("user") {
                message_count += 1;
                if first_message.is_empty() {
                    if let Some(ref content) = msg.content {
                        let text = extract_text_content(content);
                        if text != "Warmup" && !text.is_empty() {
                            first_message = text;
                        }
                    }
                }
                if first_timestamp.is_none() {
                    if let Some(ref ts) = entry.timestamp {
                        first_timestamp = ts.parse::<DateTime<Utc>>().ok();
                    }
                }
                if cwd.is_empty() {
                    if let Some(ref c) = entry.cwd {
                        cwd = c.clone();
                    }
                }
                if session_id.is_empty() {
                    if let Some(ref sid) = entry.session_id {
                        session_id = sid.clone();
                    }
                }
                if version.is_empty() {
                    if let Some(ref v) = entry.version {
                        version = v.clone();
                    }
                }
            }
            if msg.role.as_deref() == Some("assistant") && model.is_empty() {
                if let Some(ref m) = msg.model {
                    model = m.clone();
                }
            }
        }
    }

    if first_message.is_empty() && summary.is_empty() {
        return None;
    }

    if session_id.is_empty() {
        session_id = path
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default();
    }

    Some(ConversationInfo {
        session_id,
        summary,
        first_message,
        timestamp: first_timestamp,
        cwd,
        model,
        version,
        message_count,
        is_agent,
        project_dir: project_dir.to_string(),
        file_path: path.clone(),
    })
}

fn shorten_model(model: &str) -> String {
    if model.contains("opus") {
        let ver = if model.contains("4-6") || model.contains("4.6") {
            "4.6"
        } else if model.contains("4-5") || model.contains("4.5") {
            "4.5"
        } else {
            ""
        };
        format!("opus {ver}")
    } else if model.contains("sonnet") {
        let ver = if model.contains("4-6") || model.contains("4.6") {
            "4.6"
        } else if model.contains("4-5") || model.contains("4.5") {
            "4.5"
        } else if model.contains("3-5") || model.contains("3.5") {
            "3.5"
        } else {
            ""
        };
        format!("sonnet {ver}")
    } else if model.contains("haiku") {
        "haiku".to_string()
    } else if model.is_empty() {
        "-".to_string()
    } else {
        model.to_string()
    }
}

fn shorten_path(path: &str) -> String {
    let home = dirs::home_dir()
        .map(|h| h.to_string_lossy().to_string())
        .unwrap_or_default();
    if !home.is_empty() && path.starts_with(&home) {
        format!("~{}", &path[home.len()..])
    } else {
        path.to_string()
    }
}

fn short_project(path: &str) -> String {
    let p = path.trim_start_matches("~/");
    let parts: Vec<&str> = p.split('/').collect();
    if parts.len() <= 2 {
        path.to_string()
    } else {
        format!("…/{}", parts[parts.len() - 2..].join("/"))
    }
}

fn decode_project_dir(encoded: &str) -> String {
    encoded.replacen('-', "/", 1).replace('-', "/")
}

fn relative_time(dt: DateTime<Utc>) -> String {
    let now = Utc::now();
    let dur = now.signed_duration_since(dt);
    let mins = dur.num_minutes();
    let hours = dur.num_hours();
    let days = dur.num_days();

    if mins < 1 {
        "just now".to_string()
    } else if mins < 60 {
        format!("{mins}m ago")
    } else if hours < 24 {
        format!("{hours}h ago")
    } else if days < 7 {
        format!("{days}d ago")
    } else if days < 30 {
        format!("{}w ago", days / 7)
    } else if days < 365 {
        format!("{}mo ago", days / 30)
    } else {
        format!("{}y ago", days / 365)
    }
}

fn collect_sessions_from(dir: &PathBuf, out: &mut Vec<(PathBuf, String)>) {
    if !dir.exists() {
        return;
    }
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            if entry.file_type().map(|ft| ft.is_dir()).unwrap_or(false) {
                let project_name = entry.file_name().to_string_lossy().to_string();
                if let Ok(files) = fs::read_dir(entry.path()) {
                    for file in files.flatten() {
                        let path = file.path();
                        if path.extension().and_then(|e| e.to_str()) == Some("jsonl") {
                            out.push((path, project_name.clone()));
                        }
                    }
                }
            }
        }
    }
}

fn pad_or_truncate(s: &str, width: usize) -> String {
    let chars: Vec<char> = s.chars().collect();
    if chars.len() > width {
        if width > 1 {
            let truncated: String = chars[..width - 1].iter().collect();
            format!("{truncated}…")
        } else {
            "…".to_string()
        }
    } else {
        format!("{:<width$}", s)
    }
}

fn terminal_size() -> (usize, usize) {
    #[cfg(unix)]
    {
        use std::mem;
        #[repr(C)]
        struct Winsize {
            ws_row: u16,
            ws_col: u16,
            ws_xpixel: u16,
            ws_ypixel: u16,
        }
        unsafe {
            let mut ws: Winsize = mem::zeroed();
            if libc_ioctl(1, 0x5413, &raw mut ws) == 0 && ws.ws_col > 0 {
                return (ws.ws_col as usize, ws.ws_row as usize);
            }
        }
    }
    (160, 40)
}

// Raw terminal mode for single-keypress reading
struct RawMode {
    original: [u8; 60], // termios struct
}

impl RawMode {
    fn enable() -> Option<Self> {
        unsafe {
            let mut original = [0u8; 60];
            if libc_tcgetattr(0, original.as_mut_ptr()) != 0 {
                return None;
            }
            let mut raw = original;
            // Disable ICANON (line buffering) and ECHO
            // c_lflag is at offset 12 on Linux x86_64
            let lflag = u32::from_ne_bytes([raw[12], raw[13], raw[14], raw[15]]);
            let new_lflag = lflag & !(0o0000002 | 0o0000010); // ~(ICANON | ECHO)
            let bytes = new_lflag.to_ne_bytes();
            raw[12] = bytes[0];
            raw[13] = bytes[1];
            raw[14] = bytes[2];
            raw[15] = bytes[3];
            // VMIN=1, VTIME=0 — read returns after 1 byte
            // c_cc starts at offset 17 on Linux x86_64
            raw[17 + 6] = 1; // VMIN
            raw[17 + 5] = 0; // VTIME
            if libc_tcsetattr(0, 0, raw.as_ptr()) != 0 {
                return None;
            }
            Some(RawMode { original })
        }
    }
}

impl Drop for RawMode {
    fn drop(&mut self) {
        unsafe {
            libc_tcsetattr(0, 0, self.original.as_ptr());
            // Ensure cursor is visible
            eprint!("{SHOW_CURSOR}");
            let _ = io::stderr().flush();
        }
    }
}

enum Key {
    Up,
    Down,
    Enter,
    Quit,
    PageUp,
    PageDown,
    Home,
    End,
    Slash,
    EditContext,
    Other,
}

fn read_key() -> Key {
    let mut buf = [0u8; 1];
    if io::stdin().read_exact(&mut buf).is_err() {
        return Key::Quit;
    }
    match buf[0] {
        b'q' | b'Q' | 3 => Key::Quit, // q, Q, Ctrl-C
        b'\r' | b'\n' => Key::Enter,
        b'k' | b'K' => Key::Up,
        b'j' | b'J' => Key::Down,
        b'e' | b'E' => Key::EditContext,
        b'g' => Key::Home,
        b'G' => Key::End,
        b'/' => Key::Slash,
        27 => {
            // Escape sequence
            let mut seq = [0u8; 2];
            if io::stdin().read_exact(&mut seq).is_err() {
                return Key::Quit;
            }
            if seq[0] == b'[' {
                match seq[1] {
                    b'A' => Key::Up,
                    b'B' => Key::Down,
                    b'5' => {
                        // Page Up: ESC [ 5 ~
                        let mut tilde = [0u8; 1];
                        let _ = io::stdin().read_exact(&mut tilde);
                        Key::PageUp
                    }
                    b'6' => {
                        // Page Down: ESC [ 6 ~
                        let mut tilde = [0u8; 1];
                        let _ = io::stdin().read_exact(&mut tilde);
                        Key::PageDown
                    }
                    b'H' => Key::Home,
                    b'F' => Key::End,
                    _ => Key::Other,
                }
            } else {
                Key::Quit // bare Escape
            }
        }
        _ => Key::Other,
    }
}

struct ColumnWidths {
    idx: usize,
    date: usize,
    rel: usize,
    title: usize,
    project: usize,
    model: usize,
    msgs: usize,
    sid: usize,
    line: usize,
}

fn calc_widths(term_width: usize) -> ColumnWidths {
    let w_idx = 3;
    let w_date = 16;
    let w_rel = 7;
    let w_model = 10;
    let w_msgs = 4;
    let w_sid = 8;
    let fixed = w_idx + w_date + w_rel + w_model + w_msgs + w_sid + 17;
    let remaining = if term_width > fixed + 20 {
        term_width - fixed
    } else {
        60
    };
    let w_title = remaining * 55 / 100;
    let w_project = remaining - w_title;
    let line = w_idx + w_date + w_rel + w_title + w_project + w_model + w_msgs + w_sid + 15;
    ColumnWidths {
        idx: w_idx,
        date: w_date,
        rel: w_rel,
        title: w_title,
        project: w_project,
        model: w_model,
        msgs: w_msgs,
        sid: w_sid,
        line,
    }
}

fn format_row(i: usize, c: &ConversationInfo, w: &ColumnWidths, selected: bool) -> String {
    let title = if !c.summary.is_empty() {
        c.summary.clone()
    } else {
        c.first_message.clone()
    };
    let title: String = title.lines().next().unwrap_or("").trim().to_string();

    let (date, rel) = if let Some(ts) = c.timestamp {
        let local: DateTime<Local> = ts.into();
        (
            local.format("%Y-%m-%d %H:%M").to_string(),
            relative_time(ts),
        )
    } else {
        ("-".to_string(), String::new())
    };

    let project = if !c.cwd.is_empty() {
        shorten_path(&c.cwd)
    } else {
        shorten_path(&decode_project_dir(&c.project_dir))
    };
    let project = short_project(&project);

    let title = pad_or_truncate(&title, w.title);
    let project = pad_or_truncate(&project, w.project);
    let rel = pad_or_truncate(&rel, w.rel);
    let model = shorten_model(&c.model);
    let idx = format!("{}", i + 1);
    let msgs = c.message_count.to_string();
    let sid = c.session_id[..8.min(c.session_id.len())].to_string();

    if selected {
        format!(
            "{BG_BLUE}{BOLD}{WHITE} {:>w$}  {:<dw$} {rel}  {title}  {project}  {model:<mw$} {msgs:>msw$}  {sid:<sw$}{RESET}",
            idx, date,
            w = w.idx, dw = w.date, mw = w.model, msw = w.msgs, sw = w.sid,
        )
    } else {
        format!(
            " {DIM}{:>w$}{RESET}  {YELLOW}{:<dw$}{RESET} {DIM}{rel}{RESET}  {BOLD}{WHITE}{title}{RESET}  {BLUE}{project}{RESET}  {MAGENTA}{model:<mw$}{RESET} {GREEN}{msgs:>msw$}{RESET}  {DIM}{sid:<sw$}{RESET}",
            idx, date,
            w = w.idx, dw = w.date, mw = w.model, msw = w.msgs, sw = w.sid,
        )
    }
}

fn resume_conversation(c: &ConversationInfo) -> ! {
    let cwd = if !c.cwd.is_empty() { &c.cwd } else { "." };

    if std::env::set_current_dir(cwd).is_err() {
        eprintln!("Warning: could not cd to {cwd}");
    }

    let err = Command::new("claudey")
        .arg("--resume")
        .arg(&c.session_id)
        .exec();

    eprintln!("Failed to exec claude: {err}");
    std::process::exit(1);
}

fn load_conversations(cli: &Cli) -> (Vec<ConversationInfo>, usize) {
    let home = dirs::home_dir().expect("Cannot determine home directory");

    let dirs = [
        home.join(".config").join("claude").join("projects"),
        home.join(".claude").join("projects"),
    ];

    let mut session_files: Vec<(PathBuf, String)> = Vec::new();
    for dir in &dirs {
        collect_sessions_from(dir, &mut session_files);
    }

    session_files.sort_by(|a, b| a.0.cmp(&b.0));
    session_files.dedup_by(|a, b| a.0 == b.0);

    let total = session_files.len();
    eprint!("\r{DIM}Scanning {total} session files...{RESET}");

    let mut conversations: Vec<ConversationInfo> = session_files
        .par_iter()
        .filter_map(|(path, project)| parse_session(path, project))
        .collect();

    eprint!("\r\x1b[K");

    if !cli.agents {
        conversations.retain(|c| !c.is_agent);
    }

    if let Some(ref term) = cli.search {
        let term_lower = term.to_lowercase();
        conversations.retain(|c| {
            c.summary.to_lowercase().contains(&term_lower)
                || c.first_message.to_lowercase().contains(&term_lower)
                || c.cwd.to_lowercase().contains(&term_lower)
                || c.model.to_lowercase().contains(&term_lower)
                || c.session_id.to_lowercase().contains(&term_lower)
                || c.project_dir.to_lowercase().contains(&term_lower)
        });
    }

    match cli.sort.as_str() {
        "project" => conversations.sort_by(|a, b| a.project_dir.cmp(&b.project_dir)),
        "model" => conversations.sort_by(|a, b| a.model.cmp(&b.model)),
        _ => conversations.sort_by(|a, b| b.timestamp.cmp(&a.timestamp)),
    }

    if let Some(n) = cli.num {
        conversations.truncate(n);
    }
    (conversations, total)
}

const ALT_SCREEN_ON: &str = "\x1b[?1049h";
const ALT_SCREEN_OFF: &str = "\x1b[?1049l";

fn run_interactive(conversations: &[ConversationInfo], total_files: usize) {
    if conversations.is_empty() {
        eprintln!("No conversations found.");
        return;
    }

    let _raw = match RawMode::enable() {
        Some(r) => r,
        None => {
            eprintln!("Failed to enable raw terminal mode.");
            return;
        }
    };

    let count = conversations.len();
    let mut cursor: usize = 0;
    let mut scroll_offset: usize = 0;

    // Enter alternate screen buffer and hide cursor
    let _ = io::stderr().write_all(format!("{ALT_SCREEN_ON}{HIDE_CURSOR}").as_bytes());
    let _ = io::stderr().flush();

    let leave = |raw: &RawMode| {
        let _ = io::stderr()
            .write_all(format!("{SHOW_CURSOR}{ALT_SCREEN_OFF}").as_bytes());
        let _ = io::stderr().flush();
        // Restore termios (raw is about to be dropped, but be explicit for exec path)
        unsafe {
            libc_tcsetattr(0, 0, raw.original.as_ptr());
        }
    };

    loop {
        let (term_width, term_height) = terminal_size();
        let w = calc_widths(term_width);

        // header(3) + col header(1) + sep(1) + sep(1) + footer(2) = 8
        let visible_rows = if term_height > 9 { term_height - 8 } else { 10 };

        // Adjust scroll to keep cursor visible
        if cursor < scroll_offset {
            scroll_offset = cursor;
        }
        if cursor >= scroll_offset + visible_rows {
            scroll_offset = cursor - visible_rows + 1;
        }

        let end = (scroll_offset + visible_rows).min(count);

        // Build entire frame into a single buffer
        let mut out = String::with_capacity(8192);

        // Move cursor home (no clear — we overwrite every line)
        out.push_str("\x1b[H");

        // Header (line 1)
        out.push_str(&format!(
            "{BOLD}{CYAN}Claude Code Conversations{RESET}  {DIM}({count} sessions from {total_files} files){RESET}\x1b[K\n"
        ));
        // Blank line (line 2)
        out.push_str("\x1b[K\n");

        // Column headers (line 3)
        out.push_str(&format!(
            "{BOLD}{DIM} {:<w_idx$}  {:<w_date$} {:<w_rel$}  {:<w_title$}  {:<w_project$}  {:<w_model$} {:>w_msgs$}  {:<w_sid$}{RESET}\x1b[K\n",
            "#", "Date", "", "Title", "Project", "Model", "Msgs", "ID",
            w_idx = w.idx, w_date = w.date, w_rel = w.rel, w_title = w.title,
            w_project = w.project, w_model = w.model, w_msgs = w.msgs, w_sid = w.sid,
        ));

        // Top separator (line 4)
        out.push_str(&format!("{DIM}{}{RESET}\x1b[K\n", "─".repeat(w.line)));

        // Data rows
        for i in scroll_offset..end {
            let selected = i == cursor;
            out.push_str(&format_row(i, &conversations[i], &w, selected));
            out.push_str("\x1b[K\n");
        }

        // If fewer rows than visible_rows, blank the rest
        for _ in (end - scroll_offset)..visible_rows {
            out.push_str("\x1b[K\n");
        }

        // Bottom separator
        out.push_str(&format!("{DIM}{}{RESET}\x1b[K\n", "─".repeat(w.line)));

        // Footer line 1: selected conversation details
        let sel = &conversations[cursor];
        let full_path = if !sel.cwd.is_empty() {
            shorten_path(&sel.cwd)
        } else {
            shorten_path(&decode_project_dir(&sel.project_dir))
        };
        out.push_str(&format!(
            "{DIM}Path: {full_path}  |  ID: {}{RESET}\x1b[K\n",
            sel.session_id,
        ));

        // Footer line 2: keybindings
        out.push_str(&format!(
            "{DIM}j/k: navigate  Enter: resume  e: edit context  /: search  q: quit{RESET}\x1b[K"
        ));

        // Single atomic write
        let _ = io::stderr().write_all(out.as_bytes());
        let _ = io::stderr().flush();

        match read_key() {
            Key::Quit => {
                leave(&_raw);
                return;
            }
            Key::Up => {
                if cursor > 0 {
                    cursor -= 1;
                }
            }
            Key::Down => {
                if cursor + 1 < count {
                    cursor += 1;
                }
            }
            Key::PageUp => {
                cursor = cursor.saturating_sub(visible_rows);
            }
            Key::PageDown => {
                cursor = (cursor + visible_rows).min(count - 1);
            }
            Key::Home => {
                cursor = 0;
            }
            Key::End => {
                cursor = count - 1;
            }
            Key::Enter => {
                leave(&_raw);
                resume_conversation(&conversations[cursor]);
            }
            Key::EditContext => {
                // Leave alt screen, run editor, then re-enter
                let _ = io::stderr()
                    .write_all(format!("{SHOW_CURSOR}{ALT_SCREEN_OFF}").as_bytes());
                let _ = io::stderr().flush();
                unsafe { libc_tcsetattr(0, 0, _raw.original.as_ptr()); }

                editor::run_editor(&conversations[cursor].file_path);

                // Re-enter raw mode and alt screen
                unsafe {
                    let mut raw = _raw.original;
                    let lflag = u32::from_ne_bytes([raw[12], raw[13], raw[14], raw[15]]);
                    let new_lflag = lflag & !(0o0000002 | 0o0000010);
                    let bytes = new_lflag.to_ne_bytes();
                    raw[12] = bytes[0]; raw[13] = bytes[1];
                    raw[14] = bytes[2]; raw[15] = bytes[3];
                    raw[17 + 6] = 1; raw[17 + 5] = 0;
                    libc_tcsetattr(0, 0, raw.as_ptr());
                }
                let _ = io::stderr()
                    .write_all(format!("{ALT_SCREEN_ON}{HIDE_CURSOR}").as_bytes());
                let _ = io::stderr().flush();
            }
            Key::Slash => {
                // Move to footer and show search prompt
                let prompt_row = visible_rows + 7; // header(3)+colhdr(1)+sep(1)+rows+sep(1)+footer1(1) = rows+7-1
                let _ = io::stderr().write_all(
                    format!("\x1b[{prompt_row};1H\x1b[K{BOLD}/{RESET}").as_bytes(),
                );
                let _ = io::stderr().flush();

                let mut query = String::new();
                loop {
                    let mut buf = [0u8; 1];
                    if io::stdin().read_exact(&mut buf).is_err() {
                        break;
                    }
                    match buf[0] {
                        b'\r' | b'\n' => break,
                        27 => {
                            query.clear();
                            break;
                        }
                        127 | 8 => {
                            query.pop();
                            let _ = io::stderr().write_all(
                                format!("\x1b[{prompt_row};1H\x1b[K{BOLD}/{RESET}{query}")
                                    .as_bytes(),
                            );
                            let _ = io::stderr().flush();
                        }
                        c if c >= 32 => {
                            query.push(c as char);
                            let _ =
                                io::stderr().write_all(format!("{}", c as char).as_bytes());
                            let _ = io::stderr().flush();
                        }
                        _ => {}
                    }
                }

                if !query.is_empty() {
                    let q = query.to_lowercase();
                    for offset in 1..=count {
                        let idx = (cursor + offset) % count;
                        let c = &conversations[idx];
                        if c.summary.to_lowercase().contains(&q)
                            || c.first_message.to_lowercase().contains(&q)
                            || c.cwd.to_lowercase().contains(&q)
                        {
                            cursor = idx;
                            break;
                        }
                    }
                }
            }
            Key::Other => {}
        }
    }
}

fn main() {
    let cli = Cli::parse();
    let (conversations, total_files) = load_conversations(&cli);

    if cli.json {
        if conversations.is_empty() {
            println!("[]");
        } else {
            println!("{}", serde_json::to_string_pretty(&conversations).unwrap());
        }
        return;
    }

    run_interactive(&conversations, total_files);
}

#[cfg(unix)]
unsafe extern "C" {
    #[link_name = "ioctl"]
    fn libc_ioctl(fd: i32, request: u64, ...) -> i32;
    #[link_name = "tcgetattr"]
    fn libc_tcgetattr(fd: i32, termios: *mut u8) -> i32;
    #[link_name = "tcsetattr"]
    fn libc_tcsetattr(fd: i32, action: i32, termios: *const u8) -> i32;
}
