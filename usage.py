"""Token usage read from Claude Code transcripts (~/.claude/projects/*/*.jsonl)."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
WINDOW_SECONDS = 5 * 3600
_cache = {}  # path -> ((mtime_ns, size), {msg_id: entry})


def _parse(path):
    """Return {message id: (ts, model, input, output, cache_read, cache_write)}; last write wins."""
    entries = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
                msg = d["message"]
                u = msg["usage"]
                ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
            except (ValueError, KeyError, TypeError):
                continue
            key = msg.get("id") or d.get("uuid")
            entries[key] = (
                ts,
                msg.get("model", "?"),
                u.get("input_tokens", 0),
                u.get("output_tokens", 0),
                u.get("cache_read_input_tokens", 0),
                u.get("cache_creation_input_tokens", 0),
            )
    return entries


def _entries(path):
    st = path.stat()
    sig = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    data = _parse(path)
    _cache[path] = (sig, data)
    return data


def _sum(entries):
    return {
        "input": sum(e[2] for e in entries),
        "output": sum(e[3] for e in entries),
        "cache_read": sum(e[4] for e in entries),
        "cache_write": sum(e[5] for e in entries),
    }


def collect():
    """Usage for the newest session plus a rolling 5h total; None if no transcripts exist."""
    files = []
    for p in PROJECTS.glob("*/*.jsonl"):
        try:
            files.append((p.stat().st_mtime, p))
        except OSError:
            pass
    if not files:
        return None
    files.sort(reverse=True)
    now = time.time()

    session = sorted(_entries(files[0][1]).values())
    window = []
    for mtime, p in files:
        if now - mtime > WINDOW_SECONDS:
            break
        window += [e for e in _entries(p).values() if now - e[0] <= WINDOW_SECONDS]

    last = session[-1] if session else None
    return {
        "project": files[0][1].parent.name,
        "model": last[1] if last else "?",
        "turns": len(session),
        "session": _sum(session),
        "context": (last[2] + last[4] + last[5]) if last else 0,
        "duration": (session[-1][0] - session[0][0]) if session else 0,
        "window": _sum(window),
        "window_turns": len(window),
    }
