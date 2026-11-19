#!/usr/bin/env python3
"""Clawd: mascote de desktop em pixel art que reage ao Claude Code (PyQt6).

Janela transparente, sem borda e sempre no topo. Os hooks do Claude Code escrevem o estado atual em
STATE_FILE (veja clawd-hook.py) e o mascote lê esse arquivo.

- clique = carinho | arrastar = mover | roda do mouse = tamanho | duplo clique = menu (correção do ditado, som, uso, sair)
- quando está parado, passeia pela tela e volta ao canto inferior direito (CLAWD_ANDAR=0 desliga)
- os quadros vêm de sprites/ (veja tools/montar_frente.py)
"""
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

# Wayland ignora "sempre no topo" e posicionamento; o XWayland respeita os dois.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import habitos  # noqa: E402
import skins  # noqa: E402
import usage  # noqa: E402
from datetime import datetime  # noqa: E402

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPixmap, QPolygonF, QTransform  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
STATE_FILE = RUNTIME / "clawd.state"
MUTE = Path.home() / ".clawd-mute"
SKIN_FILE = Path.home() / ".clawd-skin"  # nome da pasta da skin escolhida (vazio = padrão)
HAIKU = Path.home() / ".clawd-haiku"  # existe = o ditado manda o texto ao Claude Haiku para corrigir
PACK = HERE / "sprites"

PTT = RUNTIME / "clawd.gravando"  # ditado gravando: ele não fala por cima
GRAVIDADE = 2600.0  # px/s² (com zoom 1) na queda depois de soltar
SPRITE_W, SPRITE_H, PAD = 190, 120, 10  # tamanho lógico do mascote com zoom 1
HAPPY_SECONDS = 4.0
ALERT_MAX = 120.0
SLEEP_AFTER = 300.0  # segundos parado até cochilar
USAGE_REFRESH_MS = 3000
INK = QColor(24, 18, 22)

# --- quadros -----------------------------------------------------------------------------------------------
# Folhas (8 colunas x 4 linhas, 32 quadros): o quadro n da folha X vira "X{n}".
#   c = costas          d = direita, ações     e = direita, emoções
#   f = frente 1        g = frente 2
#   h = frente, trabalho   i = frente, ócio   j = frente, extras
#   k = arrastar e dormir (pendurado, caindo, pouso, dormindo deitado)
# Um quadro com "~" na frente sai espelhado (lado esquerdo).


def R(sheet, a, b, mirror=False):  # quadros a..b (inclusive) da folha
    return [("~" if mirror else "") + f"{sheet}{i}" for i in range(a, b + 1)]


# nome -> (fps, [quadros]). Uma lista com 1 quadro = pose parada.
ANIMS = {
    # --- estados (o que o Claude está fazendo) ---
    "neutral":   (4.0, R("f", 0, 7)),
    "thinking":  (3.0, R("g", 8, 15)),
    "coding":    (6.0, R("h", 0, 7)),
    "alert":     (5.0, R("f", 25, 30)),
    "listening": (4.0, R("h", 8, 15)),
    "sleep":     (1.5, R("g", 24, 30)),
    # --- felizes (clique / fim de tarefa) ---
    "feliz":     (5.0, R("f", 8, 15)),
    "risada":    (5.0, ["f10", "f11", "f12", "f13", "f12", "f11"]),
    "amor":      (4.0, R("g", 16, 23)),
    "festa":     (5.0, R("d", 16, 23)),
    "sucesso":   (5.0, R("h", 16, 23)),
    "feliz_lado": (5.0, R("e", 8, 15)),
    # --- variações de ócio ---
    "triste":     (3.0, R("f", 16, 23)),
    "bravo":      (4.0, R("g", 0, 7)),
    "pensando":   (3.0, R("g", 8, 15)),
    "sonolento":  (2.0, R("g", 24, 27) + ["g27", "g26", "g25"]),
    "susto":      (5.0, R("f", 24, 31)),
    "apaixonado": (4.0, R("g", 16, 23)),
    "ideia":      (2.0, R("e", 20, 23)),
    "conversa":   (2.0, R("e", 17, 19)),
    "pensando_lado": (3.0, R("e", 16, 23)),
    "alerta_lado": (5.0, R("e", 25, 29)),
    "codigo":     (4.0, R("d", 24, 31)),
    "comemorar":  (5.0, R("h", 24, 31)),
    "ler":        (3.0, R("i", 0, 7)),
    "cafe":       (3.0, R("i", 8, 15)),
    "ferramenta": (4.0, R("i", 16, 23)),
    "oculos":     (3.0, R("i", 24, 31)),
    "joia":       (4.0, R("j", 0, 7)),
    "magia":      (4.0, R("j", 8, 15)),
    "musica":     (4.0, R("j", 16, 23)),
    "acenar":     (4.0, R("j", 24, 31)),
    "lado_dir":   (3.0, R("e", 0, 7)),
    "lado_esq":   (3.0, R("e", 0, 7, True)),
    "costas":     (3.0, R("c", 0, 15)),
    "costas_digitando": (6.0, R("c", 16, 23)),
    "virar":      (4.0, R("c", 24, 31)),
    "caminhar":   (7.0, R("d", 0, 7)),
    "caminhar_esq": (7.0, R("d", 0, 7, True)),
    "andar":      (8.0, R("d", 8, 15)),
    "andar_esq":  (8.0, R("d", 8, 15, True)),
    "dormindo":   (2.0, R("k", 24, 31)),     # deitado, respirando e com os Z
    "pendurado":  (6.0, R("k", 0, 7)),       # segurado no ar pelo mouse
    "caindo":     (8.0, R("k", 8, 15)),      # solto no ar
    "pouso!":     (6.0, R("k", 16, 23)),     # "!" = toca uma vez só, a partir de owner._pouso
    "especial":   (5.0, R("d", 16, 23)),
    "pulo_esq":   (5.0, R("d", 16, 23, True)),
}
ALIAS = {"original": "neutral"}

# estado (escrito pelos hooks) -> animação
STATE_SPRITE = {"idle": "neutral", "thinking": "thinking", "working": "coding",
                "alert": "alert", "happy": "feliz", "listening": "listening",
                # eventos detalhados (clawd-hook.py)
                "reading": "ler", "searching": "oculos", "testing": "ferramenta",
                "tests_ok": "comemorar", "tests_fail": "triste", "error": "susto"}
STATES = set(STATE_SPRITE)
EVENT_SECONDS = {"tests_ok": 3.5, "tests_fail": 3.5, "error": 2.5}  # depois voltam para "thinking"
HAPPY_SPRITES = ("feliz", "risada", "amor", "festa", "sucesso", "feliz_lado", "comemorar", "joia")
IDLE_VARIANTS = ("triste", "bravo", "pensando", "sonolento", "susto", "apaixonado", "ideia", "conversa",
                 "pensando_lado", "alerta_lado", "codigo", "lado_dir", "lado_esq", "costas", "virar",
                 "caminhar", "caminhar_esq", "andar", "andar_esq", "especial", "pulo_esq",
                 "ler", "cafe", "ferramenta", "oculos", "magia", "musica", "acenar")

# transições: (de, para) -> (animação de ligação, segundos); "*" vale para qualquer outra animação
TRANSICOES = {
    ("*", "dormindo"): ("sonolento", 2.0),   # cochila antes de dormir
    ("dormindo", "*"): ("susto", 0.8),       # acorda assustado
    ("*", "costas"): ("virar", 0.8),         # vira de costas
    ("costas", "*"): ("virar", 0.8),
}

# passeio pela tela
WALK_ON = os.environ.get("CLAWD_ANDAR", "1") != "0"   # CLAWD_ANDAR=0 desliga
WALK_SPEED = 110          # px/s com zoom 1
WALK_MIN = 150            # menor trecho que vale a pena andar (px, com zoom 1)
WALK_PAUSE = 3.5          # segundos acenando no ponto mais distante
WALK_EVERY = (20, 50)     # segundos de pausa entre passeios


class SheetSprites:
    """Entrega o quadro certo de cada animação conforme o relógio da janela."""

    def __init__(self, owner):
        self.owner = owner
        self.skin = ""   # pasta em skins/ ("" = a padrão, sprites/)
        self._pm = {}

    def trocar_skin(self, pasta):
        self.skin = pasta
        self._pm.clear()

    def _frame(self, key):
        if key not in self._pm:
            img = skins.quadro(key.lstrip("~"), self.skin)
            qi = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, QImage.Format.Format_RGBA8888)
            pm = QPixmap.fromImage(qi.copy())
            self._pm[key] = pm.transformed(QTransform().scale(-1, 1)) if key.startswith("~") else pm
        return self._pm[key]

    def get(self, name, default=None):
        name = ALIAS.get(name, name)
        if name not in ANIMS:
            return default
        fps, frames = ANIMS[name]
        if name.endswith("!"):  # toca uma vez, desde o pouso, e fica no último quadro
            i = int(max(0.0, time.monotonic() - self.owner._pouso) * fps)
            return self._frame(frames[min(i, len(frames) - 1)])
        return self._frame(frames[int(self.owner.t * fps) % len(frames)])

    __getitem__ = get


# --- painéis -------------------------------------------------------------------------------------------------

VERDE, AMBAR, VERMELHO = QColor(110, 220, 130), QColor(255, 190, 90), QColor(255, 105, 95)
MUTED, TEXTO, TRILHO = QColor(160, 154, 176), QColor(238, 234, 245), QColor(58, 54, 72)
DIAS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def cor_pct(p):
    return VERDE if p < 60 else AMBAR if p < 85 else VERMELHO


def fmt_dur(sec):
    m = max(0, int(sec // 60))
    if m >= 1440:
        return f"{m // 1440}d {m % 1440 // 60}h"
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m} min"


def fmt_reset(ts, semana):
    dt = datetime.fromtimestamp(ts)
    return f"{DIAS[dt.weekday()]} {dt:%H:%M}" if semana else f"{dt:%H:%M}"


def fmt_tokens(n):
    return f"{n / 1e6:g}M" if n >= 1e6 else f"{n / 1e3:g}k" if n >= 1e3 else str(int(n))


class Barra(QWidget):
    """Título + porcentagem + barra de progresso (com a projeção até a renovação) + até duas linhas de texto."""

    def __init__(self, titulo):
        super().__init__()
        self.titulo, self.pct, self.proj, self.linhas = titulo, 0.0, None, []
        self.setFixedSize(300, 76)

    def set(self, pct, proj, linhas):
        self.pct, self.proj, self.linhas = pct, proj, linhas
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cor = cor_pct(self.pct)
        f = QFont("sans", 10, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(TEXTO)
        p.drawText(QRectF(0, 0, 220, 20), Qt.AlignmentFlag.AlignVCenter, self.titulo)
        p.setPen(cor)
        p.drawText(QRectF(180, 0, 120, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f"{self.pct:.0f}%")
        bar = QRectF(0, 25, 300, 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(TRILHO)
        p.drawRoundedRect(bar, 6, 6)
        if self.proj and self.proj > self.pct:  # onde ele deve chegar até a renovação (faixa clara)
            c2 = QColor(cor_pct(min(self.proj, 100)))
            c2.setAlpha(90)
            p.setBrush(c2)
            p.drawRoundedRect(QRectF(0, 25, 300 * min(self.proj, 100) / 100, 12), 6, 6)
        if self.pct > 0:
            p.setBrush(cor)
            p.drawRoundedRect(QRectF(0, 25, max(12.0, 300 * min(self.pct, 100) / 100), 12), 6, 6)
        p.setFont(QFont("sans", 9))
        for i, (txt, c) in enumerate(self.linhas[:2]):
            p.setPen(c or MUTED)
            p.drawText(QRectF(0, 41 + i * 17, 300, 17), Qt.AlignmentFlag.AlignVCenter, txt)


SKIN_B = ("...X...", "..XXX..", ".XXXXX.", "XXXXXXX", ".XXXXX.", "..XXX..", "...X...")
HAIKU_H = ("X.....X", "X.....X", "X.....X", "XXXXXXX", "X.....X", "X.....X", "X.....X")
SPK = ("....X....", "...XX.X..", "XXXXX..X.", "XXXXX.X.X", "XXXXX.X.X", "XXXXX..X.", "...XX.X..", "....X....")
SPK_OFF = ("....X....", "...XX....", "XXXXX....", "XXXXX....", "XXXXX....", "XXXXX....", "...XX....", "....X....")
CROSS = ("X.....X", ".X...X.", "..X.X..", "...X...", "..X.X..", ".X...X.", "X.....X")


def pixel_button(p, key, r, on, hover, t):
    """Botão quadrado em pixel art: células de 2 px, borda grossa + relevo, ícone em bitmap."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    u = 2.0
    x0, y0 = round(r.x()), round(r.y())
    n = 14  # 14 células = 28 px
    if key == "quit":
        face, fg = QColor(206, 74, 66), QColor(255, 244, 240)
    elif on:
        face = {"haiku": QColor(190, 150, 255), "skin": QColor(255, 150, 200)}.get(key, QColor(255, 190, 120))
        fg = QColor(18, 22, 36)
    else:
        face, fg = QColor(58, 54, 68), QColor(170, 166, 180)
    if hover:
        face = face.lighter(118)
    hi, lo = face.lighter(135), face.darker(150)

    def cell(cx, cy, c, w=1, h=1):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRect(QRectF(x0 + cx * u, y0 + cy * u, w * u, h * u))

    cell(1, 0, INK, n - 2, 1); cell(1, n - 1, INK, n - 2, 1)      # borda (cantos cortados = visual pixel)
    cell(0, 1, INK, 1, n - 2); cell(n - 1, 1, INK, 1, n - 2)
    cell(1, 1, face, n - 2, n - 2)
    cell(1, 1, hi, n - 2, 1); cell(1, 1, hi, 1, n - 2)             # relevo
    cell(1, n - 2, lo, n - 2, 1); cell(n - 2, 1, lo, 1, n - 2)

    def bitmap(rows, ox, oy, c):
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch == "X":
                    cell(ox + i, oy + j, c)

    if key == "skin":
        bitmap(SKIN_B, 3, 3, fg)
    elif key == "haiku":
        bitmap(HAIKU_H, 3, 3, fg)
    elif key == "quit":
        bitmap(CROSS, 3, 3, fg)
    elif on:
        bitmap(SPK, 2, 3, fg)
    else:
        bitmap(SPK_OFF, 1, 3, fg)
        bitmap(CROSS, 5, 4, QColor(255, 110, 100))
    p.restore()


class ToggleBar(QWidget):
    """Botões do menu, cada um com a legenda do estado atual embaixo: Haiku/Local, Voz/Mudo, Sair."""
    KEYS = ("skin", "haiku", "speak", "quit")
    DICAS = {"skin": "Skin: {}", "haiku": "Correção do ditado: {}", "speak": "Fala do Clawd: {}", "quit": "Sair"}

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.hover = None
        self.setMouseTracking(True)
        self.setFixedSize(300, 56)
        QTimer(self, interval=250, timeout=self.update).start()

    def rects(self):
        return {k: QRectF(14 + i * 72, 1, 28, 28) for i, k in enumerate(self.KEYS)}

    def at(self, pos):
        return next((k for k, r in self.rects().items() if r.contains(QPointF(pos))), None)

    def paintEvent(self, _):
        p = QPainter(self)
        o = self.owner
        legenda = {"skin": o.skin_nome()[:9], "haiku": "Haiku" if o.haiku_on else "Local", "speak": "Voz" if o.speak_on else "Mudo", "quit": "Sair"}
        for k, r in self.rects().items():
            on = o.haiku_on if k == "haiku" else o.speak_on if k == "speak" else True
            pixel_button(p, k, r, on, self.hover == k, o.t)
            p.setPen(TEXTO if on or k == "quit" else MUTED)
            p.setFont(QFont("sans", 9))
            p.drawText(QRectF(r.center().x() - 40, 33, 80, 18), Qt.AlignmentFlag.AlignCenter, legenda[k])

    def mouseMoveEvent(self, e):
        self.hover = self.at(e.position())
        o = self.owner
        estado = {"skin": f"{o.skin_nome()} (clique para trocar)", "haiku": "Haiku (envia o texto à Anthropic)" if o.haiku_on else "local (nada sai do computador)",
                  "speak": "ligada" if o.speak_on else "desligada"}
        self.setToolTip(self.DICAS[self.hover].format(estado.get(self.hover, "")) if self.hover else "")
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.hover else Qt.CursorShape.ArrowCursor)
        self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mouseReleaseEvent(self, e):
        k = self.at(e.position())
        if k == "quit":
            QApplication.quit()
        elif k:
            self.owner.toggle(k)
            self.update()


class MenuPanel(QWidget):
    """Menu do duplo clique: botões, limites do plano (5 h e semana) com projeção, e o contexto da conversa."""

    def __init__(self, owner):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.owner = owner
        self.closed_at = 0.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 14)
        lay.setSpacing(6)
        self.titulo = QLabel()
        self.titulo.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.titulo)
        lay.addWidget(ToggleBar(owner), 0, Qt.AlignmentFlag.AlignHCenter)
        self.cinco, self.semana, self.ctx = Barra("Limite de 5 horas"), Barra("Limite da semana"), Barra("Contexto da conversa")
        for b in (self.cinco, self.semana, self.ctx):
            lay.addWidget(b)
        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        self.aviso.setFixedWidth(300)
        self.aviso.setStyleSheet("color:#a09ab0; font-size:9pt;")
        lay.addWidget(self.aviso)
        self.conq = QLabel()
        self.conq.setWordWrap(True)
        self.conq.setFixedWidth(300)
        self.conq.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.conq)
        self.timer = QTimer(self, interval=USAGE_REFRESH_MS, timeout=self.refresh)

    def refresh(self):
        lim = usage.limites()
        modelo = f"<span style='color:#a09ab0; font-size:9pt'>&nbsp;&nbsp;{lim['modelo']}</span>" if lim and lim.get("modelo") else ""
        self.titulo.setText("<span style='color:#ff9a3c; font-size:13pt; font-weight:bold'>Clawd</span>" + modelo)
        agora = time.time()
        c5, sem = (lim or {}).get("cinco_horas"), (lim or {}).get("semana")
        self.cinco.setVisible(bool(c5))
        self.semana.setVisible(bool(sem))
        if c5:
            self.cinco.set(c5["pct"], c5["projecao"], self._linhas(c5, agora, False))
        if sem:
            self.semana.set(sem["pct"], sem["projecao"], self._linhas(sem, agora, True))
        pc = (lim or {}).get("contexto_pct")
        self.ctx.setVisible(pc is not None)
        if pc is not None:
            tam = lim.get("contexto_tamanho")
            self.ctx.set(float(pc), None, [(f"de {fmt_tokens(tam)} tokens; ao encher, compacta" if tam else "", None)])
        if not lim or not (c5 or sem):
            self.aviso.setText("Sem dados dos limites ainda. Eles chegam pelo statusLine do Claude Code "
                               "(veja o README) assim que você usar o Claude.")
        elif lim["idade"] > 600:
            self.aviso.setText(f"Dados de há {fmt_dur(lim['idade'])}: atualizam quando o Claude Code está em uso.")
        else:
            self.aviso.setText("")
        self.aviso.setVisible(bool(self.aviso.text()))
        lista = self.owner.habitos.lista()
        feitas = [n for n, _, ok in lista if ok]
        faltam = [n for n, _, ok in lista if not ok]
        self.conq.setText(
            f"<span style='color:#ff9a3c; font-weight:bold'>★ Conquistas {len(feitas)}/{len(lista)}</span>"
            + (f"<br><span style='color:#eeeaf5; font-size:9pt'>{' · '.join(feitas)}</span>" if feitas else "")
            + (f"<br><span style='color:#6f6a80; font-size:9pt'>{' · '.join(faltam)}</span>" if faltam else ""))
        self.adjustSize()

    @staticmethod
    def _linhas(j, agora, semana):
        if j["renovou"]:
            return [("Janela renovada: o consumo voltou a zero.", VERDE)]
        L = []
        if j["reset"]:
            L.append((f"Renova {fmt_reset(j['reset'], semana)}  ·  em {fmt_dur(j['reset'] - agora)}", None))
        if j["esgota_em"] is not None:
            L.append((f"No ritmo atual, acaba em {fmt_dur(j['esgota_em'])}, antes de renovar", VERMELHO))
        elif j["projecao"] is not None:
            L.append((f"No ritmo atual, chega a ~{j['projecao']:.0f}% até renovar", cor_pct(j["projecao"])))
        else:
            L.append(("Ritmo: juntando dados para estimar…", None))
        return L

    def show_beside(self, anchor):
        self.refresh()
        screen = anchor.screen().availableGeometry()
        x = anchor.x() - self.width() - 8
        if x < screen.left():
            x = anchor.x() + anchor.width() + 8
        y = max(screen.top(), min(anchor.y(), screen.bottom() - self.height()))
        self.move(x, y)
        self.show()
        self.timer.start()

    def hideEvent(self, e):
        self.timer.stop()
        self.closed_at = time.monotonic()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(255, 154, 60, 150))
        p.setBrush(QColor(28, 25, 36, 247))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 16, 16)


class Balao(QWidget):
    """Balãozinho de texto acima (ou abaixo) do mascote; não pega cliques."""

    def __init__(self, dono):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.dono, self.texto, self.ate = dono, "", 0.0
        self.fonte = QFont("sans", 10, QFont.Weight.DemiBold)

    def mostrar(self, texto, seg):
        self.texto, self.ate = texto, time.monotonic() + seg
        r = QFontMetrics(self.fonte).boundingRect(QRect(0, 0, 230, 400), Qt.TextFlag.TextWordWrap, texto)
        self.resize(r.width() + 44, r.height() + 30 + 8)
        self.posicionar()
        self.show()

    def posicionar(self):
        d, geo = self.dono, self.dono.screen().availableGeometry()
        x = max(geo.left() + 4, min(d.x() + d.width() // 2 - self.width() // 2, geo.right() - self.width() - 4))
        self.move(x, max(geo.top() + 4, d.y() - self.height() + 6))

    def tick(self, agora):
        if self.isVisible():
            if agora >= self.ate:
                self.hide()
            else:
                self.posicionar()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        corpo = QRectF(1, 1, self.width() - 2, self.height() - 9)
        p.setPen(QColor(60, 44, 70))
        p.setBrush(QColor(255, 248, 235))
        p.drawRoundedRect(corpo, 12, 12)
        cx = self.width() / 2
        p.drawPolygon(QPolygonF([QPointF(cx - 6, corpo.bottom() - 1), QPointF(cx + 6, corpo.bottom() - 1),
                                 QPointF(cx, self.height() - 2)]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 248, 235))
        p.drawRect(QRectF(cx - 5, corpo.bottom() - 3, 10, 3))  # esconde a linha da base sob a ponta
        p.setPen(QColor(50, 36, 58))
        p.setFont(self.fonte)
        p.drawText(corpo.adjusted(14, 10, -14, -10), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.texto)


# --- o mascote -----------------------------------------------------------------------------------------------

class Clawd(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.zoom = 0.8
        self.sprites = SheetSprites(self)
        now = time.monotonic()
        self.t = 0.0
        self.last = now
        self.state = "idle"
        self.state_t = 0.0
        self.state_mtime = 0
        self.poll_in = 0.0
        self.idle_since = now
        self.variant = ""
        self.variant_until = 0.0
        self.next_variant = now + random.uniform(25, 60)
        self.happy_pick = random.choice(HAPPY_SPRITES)
        self.pet_until = 0.0
        self.speak_on = not MUTE.exists()
        self.haiku_on = HAIKU.exists()
        try:
            self.skin = SKIN_FILE.read_text().strip()
        except OSError:
            self.skin = ""
        if self.skin not in {p for p, _ in skins.listar()}:
            self.skin = ""
        self.sprites.trocar_skin(self.skin)
        self.drag = None
        self.press_pos = None
        self.moved = False
        self.walk = None  # {"x", "alvo", "dir": +1/-1, "volta": x do canto, "pausa": até quando acena}
        self.next_walk = now + random.uniform(10, 20)
        self._wlast = now
        self._nome_ant = ""
        self._trans = None
        self.caindo = False   # solto no ar: cai até o chão
        self._fy = self._vy = 0.0
        self._saltos = 0
        self._pouso = -9.0
        self._vx = 0.0        # velocidade do arrasto (balança o mascote pendurado)
        self._ang = 0.0
        self._ult = None
        self.habitos = habitos.Habitos()
        self.balao = Balao(self)
        self.fila_avisos = []
        self._aviso_anim = ("", 0.0)
        self._estado_ant = None
        self._lim_t = 0.0
        self.home = (0, 0)
        self.retorno = False  # interrompido longe do canto: volta deslizando
        self.panel = MenuPanel(self)
        self.apply_size()
        QTimer(self, interval=33, timeout=self.tick).start()
        self.place()
        QTimer.singleShot(6000, lambda: self.fila_avisos.extend(self.habitos.ao_iniciar(time.time())))

    # --- janela ---
    def apply_size(self):
        self.resize(round((SPRITE_W + 2 * PAD) * self.zoom), round((SPRITE_H + 2 * PAD) * self.zoom))

    def place(self):
        screens = QApplication.screens()
        geo = (screens[1] if len(screens) > 1 else screens[0]).availableGeometry()
        self.home = (geo.right() - self.width() - 20, geo.bottom() - self.height() - 20)  # canto inferior direito
        self.move(*self.home)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(500, self.hide_from_taskbar)

    def hide_from_taskbar(self):
        try:
            from Xlib import X, display, protocol
            d = display.Display()
            atom = d.intern_atom
            ev = protocol.event.ClientMessage(
                window=int(self.winId()), client_type=atom("_NET_WM_STATE"),
                data=(32, [1, atom("_NET_WM_STATE_SKIP_TASKBAR"), atom("_NET_WM_STATE_SKIP_PAGER"), 1, 0]))
            d.screen().root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            d.flush()
            d.close()
        except Exception:
            pass  # sem python-xlib (ou sem X11): só continua aparecendo na barra de tarefas

    # --- estado ---
    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_t = 0.0
            self.idle_since = time.monotonic()
            if state == "happy":
                self.happy_pick = random.choice(HAPPY_SPRITES)

    def wake(self):  # chamado pelo voice.py quando ele começa a ouvir
        self.idle_since = time.monotonic()

    def poll_state(self):
        try:
            mtime = STATE_FILE.stat().st_mtime_ns
            if mtime == self.state_mtime:
                return
            self.state_mtime = mtime
            name = STATE_FILE.read_text().strip()
        except OSError:
            return
        if name in STATES:
            self.idle_since = time.monotonic()
            if name == "happy":
                self.happy_pick = random.choice(HAPPY_SPRITES)
            self.state = name
            self.state_t = 0.0

    @property
    def sleeping(self):
        return self.state == "idle" and time.monotonic() - self.idle_since > SLEEP_AFTER

    def skin_nome(self):
        return next((n for p, n in skins.listar() if p == self.skin), "Clawd")

    def trocar_skin(self):
        """Passa para a próxima skin (e lembra a escolha)."""
        pastas = [p for p, _ in skins.listar()]
        self.skin = pastas[(pastas.index(self.skin) + 1) % len(pastas)] if self.skin in pastas else ""
        self.sprites.trocar_skin(self.skin)
        try:
            SKIN_FILE.write_text(self.skin)
        except OSError:
            pass

    def toggle(self, which):
        if which == "skin":
            self.trocar_skin()
            return
        flag = HAIKU if which == "haiku" else MUTE
        if flag.exists():
            flag.unlink(missing_ok=True)
        else:
            flag.touch()
        self.haiku_on, self.speak_on = HAIKU.exists(), not MUTE.exists()

    # --- relógio ---
    def tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self.last)
        self.last = now
        self.t += dt
        self.state_t += dt
        self.poll_in -= dt
        if self.poll_in <= 0:
            self.poll_in = 0.25
            self.poll_state()
            self.speak_on = not MUTE.exists()
            self.haiku_on = HAIKU.exists()
        if self.state == "happy" and self.state_t > HAPPY_SECONDS:
            self.set_state("idle")
        if self.state == "alert" and self.state_t > ALERT_MAX:
            self.set_state("idle")
        lim = EVENT_SECONDS.get(self.state)
        if lim and self.state_t > lim:  # fim dos testes / erro: volta a "pensando"
            self.set_state("thinking")
        if self.state == "idle" and not self.sleeping:  # de vez em quando ele faz outra coisa
            if self.variant and now > self.variant_until:
                self.variant = ""
            elif not self.variant and now > self.next_variant:
                self.variant = random.choice(IDLE_VARIANTS)
                self.variant_until = now + random.uniform(4, 7)
                self.next_variant = self.variant_until + random.uniform(5, 14)
        else:
            self.variant = ""
        self._fisica(now, dt)
        self._avisos(now)
        self._walk_tick(now)
        if self.walk:  # andando: nada de variação de ócio por cima
            self.variant = ""
            self.next_variant = max(self.next_variant, now + 8)
        self.update()

    # --- arrastar com vida: pendurado, queda e pouso ---
    @property
    def pendurado(self):
        return self.drag is not None and self.moved

    def _fisica(self, now, dt):
        self._vx *= max(0.0, 1 - dt * 6)
        alvo = max(-30.0, min(30.0, -self._vx * 0.03)) if self.pendurado else 0.0
        self._ang += (alvo - self._ang) * min(1.0, dt * 8)
        if not self.caindo:
            return
        self._vy += GRAVIDADE * self.zoom * dt
        self._fy += self._vy * dt
        chao = self._chao()
        if self._fy >= chao:
            self._fy = chao
            if self._vy > 450 * self.zoom and self._saltos < 1:  # quica uma vez
                self._vy *= -0.3
                self._saltos += 1
            else:
                self.caindo = False
                self._pouso = time.monotonic()
        self.move(self.x(), round(self._fy))

    def _chao(self):
        return self.screen().availableGeometry().bottom() - self.height() - 20  # a mesma margem do canto

    # --- hábitos, humor e conquistas ---
    def _avisos(self, now):
        agora = time.time()
        if self.state != self._estado_ant:
            self.fila_avisos += self.habitos.ao_mudar_estado(self._estado_ant, self.state, agora)
            self._estado_ant = self.state
        self.fila_avisos += self.habitos.tick(self.state, agora)
        if agora - self._lim_t >= 30:                      # limites do plano: confere a cada 30 s
            self._lim_t = agora
            self.fila_avisos += self.habitos.avisos_limites(usage.limites(), agora)
        self.balao.tick(now)
        if self.fila_avisos and not self.balao.isVisible() and not self.pendurado and not self.caindo:
            self.mostrar_aviso(self.fila_avisos.pop(0), now)

    def mostrar_aviso(self, a, now):
        self.balao.mostrar(a.texto, a.seg)
        if a.anim and self.state in ("idle", "happy"):
            self.walk = None
            self._aviso_anim = (a.anim, now + a.seg)
        if a.fala and self.speak_on and not PTT.exists():
            subprocess.Popen([sys.executable, str(HERE / "speak.py"), "--texto", a.fala],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # --- passeio ---
    def _walk_tick(self, now):
        dt = min(0.1, now - self._wlast)
        self._wlast = now
        if self.caindo or self.pendurado:
            self.walk, self.retorno = None, False
            return
        if self.walk:
            if self.state != "idle" or self.drag is not None or self.sleeping:
                self.retorno = self.drag is None  # o Claude voltou a trabalhar: volta ao canto (se não foi o mouse)
                self.walk = None
                self.next_walk = now + random.uniform(*WALK_EVERY)
                return
            w = self.walk
            if w.get("pausa"):  # parado no ponto mais distante, acenando
                if now < w["pausa"]:
                    return
                w["pausa"] = 0
            w["x"] += WALK_SPEED * self.zoom * dt * w["dir"]
            if (w["dir"] > 0 and w["x"] >= w["alvo"]) or (w["dir"] < 0 and w["x"] <= w["alvo"]):
                w["x"] = w["alvo"]
                if w["volta"] is not None:  # chegou longe: acena e retorna ao canto
                    w["alvo"], w["volta"] = w["volta"], None
                    w["dir"] = 1 if w["alvo"] > w["x"] else -1
                    w["pausa"] = now + WALK_PAUSE
                else:
                    self.walk = None
                    self.next_walk = now + random.uniform(*WALK_EVERY)
                    self.move(*self.home)
                    return
            self.move(round(w["x"]), self.y())
        elif self.retorno:
            if self.drag is not None:
                self.retorno = False
                return
            hx, hy = self.home
            x = self.x()
            passo = 3 * WALK_SPEED * self.zoom * dt
            nx = hx if abs(hx - x) <= passo else x + math.copysign(passo, hx - x)
            self.move(round(nx), hy)
            if nx == hx:
                self.retorno = False
        elif (WALK_ON and now > self.next_walk and self.state == "idle" and not self.sleeping
              and self.drag is None and not self.variant and now > self.pet_until):
            geo = self.screen().availableGeometry()
            lo, hi = geo.left(), geo.right() - self.width()
            x = self.x()
            for _ in range(6):
                alvo = random.uniform(lo, hi)
                if abs(alvo - x) >= WALK_MIN * self.zoom:
                    self.walk = {"x": float(x), "alvo": alvo, "dir": 1 if alvo > x else -1, "volta": float(self.home[0])}
                    return
            self.next_walk = now + 10  # sem espaço para andar (janela encostada nos dois lados)

    # --- qual animação ---
    def _base_sprite(self):
        if self.pendurado:
            return "pendurado"
        if self.caindo:
            return "caindo"
        if time.monotonic() - self._pouso < 1.4:  # acabou de pousar
            return "pouso!"
        if time.monotonic() < self._aviso_anim[1] and self.state in ("idle", "happy"):
            return self._aviso_anim[0]
        if self.walk and self.state == "idle" and time.monotonic() >= self.pet_until:
            if self.walk.get("pausa"):
                return "acenar"
            return "andar" if self.walk["dir"] > 0 else "andar_esq"
        if time.monotonic() < self.pet_until:
            return self.happy_pick
        if self.state == "idle":
            return "dormindo" if self.sleeping else (self.variant or "original")
        if self.state == "happy":
            return self.happy_pick
        return STATE_SPRITE[self.state]

    def current_sprite(self):
        nome = self._base_sprite()
        now = time.monotonic()
        if nome != self._nome_ant:
            ant, self._nome_ant = self._nome_ant, nome
            t = TRANSICOES.get((ant, nome)) or TRANSICOES.get((ant, "*")) or TRANSICOES.get(("*", nome))
            if t and ant and nome != t[0]:
                self._trans = (t[0], now + t[1])
        if self._trans and now < self._trans[1] and nome not in ("andar", "andar_esq", "acenar", "pendurado", "caindo", "pouso!"):
            return self._trans[0]
        return nome

    # --- desenho ---
    def extra_motion(self, name, st):
        """Movimento de vida: respiração, balanço, pulinhos, tremor ao digitar. (dx, dy, sx, sy, rot)"""
        t = self.t
        if self.walk and st == "idle":
            if self.walk.get("pausa"):
                return 0.0, 0.0, 1.0, 1.0, 0.0
            return 0.0, -abs(math.sin(t * 8)) * 3, 1.0, 1.0, 0.0  # quicando de leve ao andar
        b = math.sin(t * 2.4)
        dx = dy = rot = 0.0
        sx, sy = 1 + 0.014 * b, 1 - 0.02 * b
        if name == "dormindo":
            sx, sy = 1 + 0.01 * b, 1 - 0.03 * b
        elif st == "idle":
            rot = math.sin(t * 1.1) * 1.8
            k = (t % 9.0) / 0.5  # um pulinho a cada 9 s
            if k < 1:
                dy = -abs(math.sin(k * math.pi)) * 8
                sy *= 1 + 0.05 * math.cos(k * math.pi * 2)
        elif st == "thinking":
            rot = math.sin(t * 1.4) * 3.5
        elif st == "working":
            rot = math.sin(t * 13) * 1.3
            dx = math.sin(t * 6.5) * 1.4
        elif st == "listening":
            rot = math.sin(t * 3.1) * 3.5
        elif st == "alert":
            rot = math.sin(t * 24) * 4
        elif st == "happy":
            rot = math.sin(t * 9) * 5
        return dx, dy, sx, sy, rot

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        z, st, t = self.zoom, self.state, self.t
        name = self.current_sprite()
        pm = self.sprites.get(name) or self.sprites.get("neutral")

        area_w, area_h = (SPRITE_W + 2 * PAD) * z, (SPRITE_H + 2 * PAD) * z
        scale = min(SPRITE_W * z / pm.width(), SPRITE_H * z / pm.height())
        w, h = pm.width() * scale, pm.height() * scale
        cx, base = area_w / 2, area_h - PAD * z  # pés na linha de base

        # movimento por estado
        dx = dy = 0.0
        sx = sy = 1.0
        if name == "dormindo":
            sy = 1 + math.sin(t * 1.2) * 0.02
        elif st == "idle":
            dy = math.sin(t * 2.2) * 1.5 * z
        elif st == "thinking":
            dx = math.sin(t * 1.2) * 3 * z
            dy = math.sin(t * 1.5) * 1.5 * z
        elif st == "working":
            dy = abs(math.sin(t * 9)) * -1.8 * z
        elif st == "listening":
            dx = math.sin(t * 2.4) * 2.5 * z
            dy = math.sin(t * 3) * 1.5 * z
        elif st == "alert":
            dx = (1 if int(t * 30) % 2 else -1) * 2 * z
            dy = -abs(math.sin(t * 10)) * 6 * z
        if st == "happy" or time.monotonic() < self.pet_until:
            dy = -abs(math.sin(t * 7)) * 12 * z
            sy = 1 + 0.05 * math.sin(t * 14)

        ex = self.extra_motion(name, st)
        dx += ex[0] * z
        dy += ex[1] * z
        sx *= ex[2]
        sy *= ex[3]

        if self.pendurado:  # pendurado pela cabeça: balança como pêndulo
            p.save()
            p.translate(cx, base - h * 0.75)  # pivô no topo da cabeça (que fica a ~25% da altura do quadro)
            p.rotate(self._ang)
            p.drawPixmap(QRectF(-w / 2, -h * 0.25, w, h), pm, QRectF(pm.rect()))
            p.restore()
            return

        # sombra suave no chão
        lift = min(1.0, max(0.0, -dy / (12 * z))) if z else 0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, int(70 * (1 - 0.5 * lift))))
        sw = w * 0.62 * (1 - 0.25 * lift)
        p.drawEllipse(QRectF(cx - sw / 2, base - 3 * z, sw, 8 * z))

        p.save()
        p.translate(cx + dx, base + dy)
        p.rotate(ex[4])
        p.scale(sx, sy)
        p.drawPixmap(QRectF(-w / 2, -h, w, h), pm, QRectF(pm.rect()))
        p.restore()

        if st == "listening":  # notas musicais subindo
            p.setFont(QFont("sans", max(8, int(15 * z)), QFont.Weight.Bold))
            top = base + dy - h
            for i, ch in enumerate(("♪", "♫")):
                k = (t * 0.7 + i * 0.5) % 1
                p.setPen(QColor(110, 235, 240, int(255 * (1 - k))))
                p.drawText(QPointF(cx + dx + (-1 if i else 1) * (w * 0.38 + 6 * z), top + 24 * z - k * 22 * z), ch)

    # --- mouse ---
    def mousePressEvent(self, e):
        self.walk = None  # pegou nele: para de andar
        self.caindo = False
        self._ult = None
        self.press_pos = e.globalPosition().toPoint()
        self.moved = False
        self.drag = self.press_pos - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            if (e.globalPosition().toPoint() - self.press_pos).manhattanLength() > 4:
                self.moved = True
            if self.moved:
                g = e.globalPosition().toPoint()
                agora = time.monotonic()
                if self._ult and agora > self._ult[1]:
                    self._vx = 0.6 * self._vx + 0.4 * (g.x() - self._ult[0]) / (agora - self._ult[1])
                self._ult = (g.x(), agora)
                self.move(g - self.drag)

    def mouseReleaseEvent(self, e):
        if self.drag is not None and not self.moved:  # um clique simples = carinho
            self.pet_until = time.monotonic() + 1.8
            self.happy_pick = random.choice(HAPPY_SPRITES)
        elif self.drag is not None and self.y() < self._chao() - 4:  # soltou no ar: cai
            self.caindo, self._fy, self._vy, self._saltos = True, float(self.y()), 0.0, 0
        self.drag = None

    def wheelEvent(self, e):
        self.zoom = max(0.5, min(2.5, self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1)))
        self.apply_size()

    def mouseDoubleClickEvent(self, e):
        if not self.panel.isVisible() and time.monotonic() - self.panel.closed_at > 0.25:
            self.panel.show_beside(self)


def main():
    app = QApplication(sys.argv)
    w = Clawd()
    w.show()
    import voice  # noqa: E402
    voice.attach(w)
    import ditado  # noqa: E402
    ditado.attach(w)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
