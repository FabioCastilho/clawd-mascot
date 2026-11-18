#!/usr/bin/env python3
"""Hook do Claude Code -> estado do Clawd. Uso: clawd-hook.py <Evento>   (o JSON do hook vem no stdin)

Escreve em $XDG_RUNTIME_DIR/clawd.state um estado mais detalhado que o antigo printf:
  reading   Read/Glob/Grep           searching  WebSearch/WebFetch      testing  rodando testes
  working   Edit/Write/Bash/Task...  tests_ok / tests_fail (fim dos testes)   error  ferramenta falhou
"""
import json
import os
import re
import sys
from pathlib import Path

STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.state"
LEITURA = {"Read", "Glob", "Grep", "LS", "NotebookRead"}
WEB = {"WebSearch", "WebFetch"}
TESTE = re.compile(r"\b(pytest|py\.test|unittest|jest|vitest|mocha|cargo test|go test|npm (run )?test|yarn test|pnpm test|make test|rspec|phpunit)\b")
FALHOU = re.compile(r"(\bfailed\b|\bfailures?\b|\berrors?\b|traceback|assertionerror|\bFAIL\b|exit code [1-9])", re.I)


def texto(x):
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return str(x)


def decidir(evento, d):
    tool = d.get("tool_name", "")
    cmd = str((d.get("tool_input") or {}).get("command", "")) if isinstance(d.get("tool_input"), dict) else ""
    teste = tool == "Bash" and bool(TESTE.search(cmd))
    if evento == "PreToolUse":
        if tool in LEITURA:
            return "reading"
        if tool in WEB:
            return "searching"
        return "testing" if teste else "working"
    if evento == "PostToolUseFailure":
        return "tests_fail" if teste else "error"
    if evento == "PostToolUse":
        if teste:
            return "tests_fail" if FALHOU.search(texto(d.get("tool_response", ""))) else "tests_ok"
        return "thinking"
    return None


def main():
    evento = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        d = json.load(sys.stdin)
    except Exception:
        d = {}
    estado = decidir(evento, d) or {"Stop": "happy", "Notification": "alert", "UserPromptSubmit": "thinking",
                                    "SessionStart": "idle"}.get(evento)
    if estado:
        try:
            STATE.write_text(estado)
        except OSError:
            pass


if __name__ == "__main__":
    main()
