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


# ---------- Limites do plano (vêm do statusLine do Claude Code; veja clawd-statusline.py) ----------------------------

import os  # noqa: E402

LIMITES = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.limites.json"


def _ritmo(hist, chave_p, chave_r, reset, min_span):
    """Pontos de % por segundo na janela atual (None se ainda não dá para estimar)."""
    pts = [(a["t"], a[chave_p]) for a in hist if a.get(chave_r) == reset and a.get(chave_p) is not None]
    if len(pts) < 2:
        return None
    (t0, p0), (t1, p1) = pts[0], pts[-1]
    if t1 - t0 < min_span or p1 <= p0:
        return None
    return (p1 - p0) / (t1 - t0)


def _janela(rl, nome, hist, chave_p, chave_r, min_span, agora):
    j = (rl or {}).get(nome)
    if not j or j.get("used_percentage") is None:
        return None
    reset, pct = j.get("resets_at"), float(j["used_percentage"])
    renovou = reset is not None and reset <= agora  # o dado é de antes da renovação: já zerou
    if renovou:
        pct = 0.0
    out = {"pct": pct, "reset": reset, "renovou": renovou, "ritmo": None, "projecao": None, "esgota_em": None}
    if reset and not renovou:
        r = _ritmo(hist, chave_p, chave_r, reset, min_span)
        if r:
            out["ritmo"] = r
            out["projecao"] = pct + r * (reset - agora)          # % esperado na hora da renovação
            if out["projecao"] >= 100:
                out["esgota_em"] = (100 - pct) / r                # segundos até bater 100%
    return out


def limites():
    """Limites do plano (5h e semana) + contexto, ou None se o statusLine ainda não gravou nada."""
    try:
        d = json.loads(LIMITES.read_text())
    except (OSError, ValueError):
        return None
    agora = time.time()
    rl, hist = d.get("rate_limits"), d.get("historico", [])
    return {"idade": agora - d.get("quando", agora), "modelo": d.get("modelo"),
            "contexto_pct": d.get("contexto_pct"), "contexto_tamanho": d.get("contexto_tamanho"),
            "cinco_horas": _janela(rl, "five_hour", hist, "p5", "r5", 600, agora),
            "semana": _janela(rl, "seven_day", hist, "p7", "r7", 3600, agora)}
