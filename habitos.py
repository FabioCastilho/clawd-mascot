"""Hábitos e humor do Clawd: saudação do dia, aviso de madrugada, lembrete de descanso e conquistas.

Lógica pura (sem Qt): recebe os eventos do mascote e devolve `Aviso`s para ele mostrar. O progresso fica em
~/.local/state/clawd/estado.json.

Env: CLAWD_DESCANSO_MIN (minutos de uso contínuo até o lembrete; padrão 120; 0 desliga).
"""
import json
import os
import time
from collections import namedtuple
from datetime import date, timedelta
from pathlib import Path

ESTADO = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "clawd" / "estado.json"
DESCANSO_SEG = int(os.environ.get("CLAWD_DESCANSO_MIN", "120")) * 60
DADO_VELHO = 1800     # limites com mais de 30 min não avisam (o Claude Code não está em uso)
PAUSA_QUE_ZERA = 600  # 10 min parado = contou como pausa

Aviso = namedtuple("Aviso", "texto anim fala seg")

CONQUISTAS = {
    "primeiro_teste": ("Primeiro teste verde", "O primeiro teste que passou"),
    "consertou": ("Consertou", "Um teste falhou e depois passou"),
    "coruja": ("Coruja", "Usou o Claude de madrugada"),
    "maratonista": ("Maratonista", "Duas horas seguidas de trabalho"),
    "tres_dias": ("Constante", "Três dias seguidos usando"),
    "sete_dias": ("Hábito", "Sete dias seguidos usando"),
    "cem_pedidos": ("Cem pedidos", "100 pedidos feitos ao Claude"),
}


def _hora(agora):
    return time.localtime(agora).tm_hour


def _dia(agora):
    return date.fromtimestamp(agora)


def _noite(agora):  # a "noite" vira o dia só às 5h: 1h da manhã de terça ainda é a noite de segunda
    return (_dia(agora - 5 * 3600)).isoformat()


class Habitos:
    def __init__(self, caminho=ESTADO):
        self.caminho = Path(caminho)
        try:
            self.d = json.loads(self.caminho.read_text())
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("conquistas", {})
        self.d.setdefault("contagem", {"prompts": 0, "testes_ok": 0})
        self.d.setdefault("dias", [])
        self.inicio_trabalho = None   # começo do trecho de trabalho contínuo
        self.ultima_atividade = 0.0
        self.ultimo_lembrete = 0.0

    # --- persistência
    def salvar(self):
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.caminho.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, ensure_ascii=False))
            os.replace(tmp, self.caminho)
        except OSError:
            pass

    # --- conquistas
    def desbloquear(self, chave, agora):
        if chave in self.d["conquistas"]:
            return None
        self.d["conquistas"][chave] = _dia(agora).isoformat()
        self.salvar()
        nome = CONQUISTAS[chave][0]
        return Aviso(f"Conquista: {nome}!", "festa", f"Conquista desbloqueada: {nome}!", 6.0)

    def lista(self):
        """[(nome, descrição, desbloqueada)] na ordem de CONQUISTAS."""
        return [(n, desc, k in self.d["conquistas"]) for k, (n, desc) in CONQUISTAS.items()]

    # --- limites do plano
    def avisos_limites(self, lim, agora):
        """Balão quando um limite passa de 80% / 95% ou quando o ritmo atual vai esgotá-lo antes da renovação.
        `lim` é o resultado de usage.limites(). Cada aviso sai uma vez por janela (guardado em estado.json)."""
        if not lim or lim.get("idade", 0) > DADO_VELHO:
            return []
        feitos = self.d.setdefault("alertas", {})
        for k in [k for k, ate in feitos.items() if ate < agora]:   # limpa janelas que já renovaram
            del feitos[k]
        avisos = []
        for chave, rotulo in (("cinco_horas", "5 h"), ("semana", "semanal")):
            j = lim.get(chave)
            if not j or j.get("renovou") or not j.get("reset"):
                continue
            quando = time.strftime("%H:%M", time.localtime(j["reset"])) if j["reset"] - agora < 86400 else \
                time.strftime("%a %H:%M", time.localtime(j["reset"]))
            pct = int(j["pct"])
            for nivel in (95, 80):
                if pct >= nivel:
                    k = f"{chave}:{j['reset']}:{nivel}"
                    if not any(f.startswith(f"{chave}:{j['reset']}:") and int(f.rsplit(":", 1)[1]) >= nivel
                               for f in feitos if f.rsplit(":", 1)[1].isdigit()):
                        feitos[k] = j["reset"]
                        t = f"Limite {rotulo} em {pct}%. Renova {quando}."
                        avisos.append(Aviso(t, "alert", t, 7.0))
                    break
            if j.get("esgota_em") is not None and pct < 95:
                k = f"{chave}:{j['reset']}:proj"
                if k not in feitos:
                    feitos[k] = j["reset"]
                    m = max(1, int(j["esgota_em"] // 60))
                    dur = f"{m} min" if m < 120 else f"{m // 60} h"
                    t = f"No ritmo atual o limite {rotulo} acaba em ~{dur}, antes de renovar ({quando})."
                    avisos.append(Aviso(t, "alert", t, 9.0))
        if avisos:
            self.salvar()
        return avisos

    # --- sequência de dias
    def _registrar_dia(self, agora):
        hoje = _dia(agora).isoformat()
        dias = self.d["dias"]
        if hoje not in dias:
            dias.append(hoje)
            self.d["dias"] = dias[-30:]
            self.salvar()
        seq, dia = 0, _dia(agora)
        while dia.isoformat() in self.d["dias"]:
            seq += 1
            dia -= timedelta(days=1)
        return seq

    # --- eventos
    def ao_iniciar(self, agora):
        """Saudação, uma vez por dia (quando o mascote abre)."""
        hoje = _dia(agora).isoformat()
        if self.d.get("saudacao") == hoje:
            return []
        self.d["saudacao"] = hoje
        self.salvar()
        h = _hora(agora)
        s = "Bom dia!" if 5 <= h < 12 else "Boa tarde!" if 12 <= h < 18 else "Boa noite!"
        return [Aviso(s, "acenar", s, 5.0)]

    def ao_mudar_estado(self, ant, novo, agora):
        avisos = []
        if novo == "idle":
            return avisos
        seq = self._registrar_dia(agora)
        for chave, ok in (("tres_dias", seq >= 3), ("sete_dias", seq >= 7)):
            if ok and (a := self.desbloquear(chave, agora)):
                avisos.append(a)
        if novo == "thinking" and ant in (None, "idle", "happy", "alert"):  # um pedido novo
            self.d["contagem"]["prompts"] += 1
            self.salvar()
            if self.d["contagem"]["prompts"] >= 100 and (a := self.desbloquear("cem_pedidos", agora)):
                avisos.append(a)
        if novo == "tests_ok":
            self.d["contagem"]["testes_ok"] += 1
            if self.d.get("ultimo_teste") == "fail" and (a := self.desbloquear("consertou", agora)):
                avisos.append(a)
            if a := self.desbloquear("primeiro_teste", agora):
                avisos.append(a)
            self.d["ultimo_teste"] = "ok"
            self.salvar()
        elif novo == "tests_fail":
            self.d["ultimo_teste"] = "fail"
            self.salvar()
        if _hora(agora) < 5:
            if a := self.desbloquear("coruja", agora):
                avisos.append(a)
            if novo == "happy" and self.d.get("madrugada") != _noite(agora):  # terminou uma tarefa tarde da noite
                self.d["madrugada"] = _noite(agora)
                self.salvar()
                t = "Já é tarde! Que tal descansar?"
                avisos.append(Aviso(t, "sonolento", t, 6.0))
        return avisos

    def tick(self, estado, agora):
        """Chamado o tempo todo: controla o trabalho contínuo e o lembrete de descanso."""
        if estado != "idle":
            if self.inicio_trabalho is None:
                self.inicio_trabalho = agora
            self.ultima_atividade = agora
        elif self.inicio_trabalho is not None and agora - self.ultima_atividade > PAUSA_QUE_ZERA:
            self.inicio_trabalho = None
        if not DESCANSO_SEG or self.inicio_trabalho is None or estado not in ("idle", "happy"):
            return []
        trabalhou = agora - self.inicio_trabalho
        if trabalhou >= DESCANSO_SEG and agora - self.ultimo_lembrete >= DESCANSO_SEG:
            self.ultimo_lembrete = agora
            avisos = []
            if trabalhou >= 2 * 3600 and (a := self.desbloquear("maratonista", agora)):
                avisos.append(a)
            h, m = int(trabalhou // 3600), int(trabalhou % 3600 // 60)
            t = f"Você está nessa há {h}h{m:02d}. Que tal uma pausa?"
            avisos.insert(0, Aviso(t, "cafe", t, 8.0))
            return avisos
        return []
