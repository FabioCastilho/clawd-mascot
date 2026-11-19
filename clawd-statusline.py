#!/usr/bin/env python3
"""statusLine do Claude Code: guarda os limites de uso do plano (janela de 5h e semanal) para o Clawd mostrar no menu.

O Claude Code passa um JSON por stdin a cada atualização da linha de status; aqui copiamos o que interessa
(`rate_limits`, contexto, modelo) para $XDG_RUNTIME_DIR/clawd.limites.json, junto de um pequeno histórico que o
Clawd usa para estimar o ritmo de consumo. Não imprime nada (a linha de status fica vazia).
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

DEST = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.limites.json"
HIST_SEGUNDOS = 8 * 24 * 3600   # a semana inteira
HIST_MIN_INTERVALO = 120        # no máximo uma amostra a cada 2 min (ou quando o valor muda)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    agora = time.time()
    rl = data.get("rate_limits") or {}
    h5, h7 = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    ctx = data.get("context_window") or {}
    try:
        antigo = json.loads(DEST.read_text())
    except (OSError, ValueError):
        antigo = {}
    hist = [a for a in antigo.get("historico", []) if agora - a["t"] < HIST_SEGUNDOS]
    amostra = {"t": agora, "p5": h5.get("used_percentage"), "r5": h5.get("resets_at"),
               "p7": h7.get("used_percentage"), "r7": h7.get("resets_at")}
    if amostra["p5"] is not None and (not hist or agora - hist[-1]["t"] >= HIST_MIN_INTERVALO
                                      or (hist[-1]["p5"], hist[-1]["p7"]) != (amostra["p5"], amostra["p7"])):
        hist.append(amostra)
    out = {"quando": agora, "rate_limits": rl or None, "modelo": (data.get("model") or {}).get("display_name"),
           "contexto_pct": ctx.get("used_percentage"), "contexto_tamanho": ctx.get("context_window_size"),
           "historico": hist}
    fd, tmp = tempfile.mkstemp(dir=DEST.parent, prefix=".clawd-lim-")
    with os.fdopen(fd, "w") as f:
        json.dump(out, f)
    os.replace(tmp, DEST)


if __name__ == "__main__":
    main()
