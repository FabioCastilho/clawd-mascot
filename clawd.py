#!/usr/bin/env python3
"""Clawd: mascote de desktop em pixel art que reage ao Claude Code (PyQt6).

Janela transparente, sem borda e sempre no topo. Os hooks do Claude Code escrevem o estado atual em
STATE_FILE (veja clawd-hook.py) e o mascote lê esse arquivo.

- clique = carinho | arrastar = mover | roda do mouse = tamanho | duplo clique = menu (voz, som, uso, sair)
- quando está parado, passeia pela tela e volta ao canto inferior direito (CLAWD_ANDAR=0 desliga)
- os quadros vêm de sprites/ (veja tools/montar_frente.py)
"""
import math
import os
import random
import sys
import time
from pathlib import Path

# Wayland ignora "sempre no topo" e posicionamento; o XWayland respeita os dois.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import usage  # noqa: E402

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap, QTransform  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
STATE_FILE = RUNTIME / "clawd.state"
VOICE_ON = RUNTIME / "clawd.voice-on"
MUTE = Path.home() / ".clawd-mute"
PACK = HERE / "sprites"

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
    "especial":   (5.0, R("d", 16, 23)),
    "pulo_esq":   (5.0, R("d", 16, 23, True)),
}
ALIAS = {"original": "neutral", "dormindo": "sleep"}

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
        self._pm = {}

    def _frame(self, key):
        if key not in self._pm:
            pm = QPixmap(str(PACK / f"{key.lstrip('~')}.png"))
            self._pm[key] = pm.transformed(QTransform().scale(-1, 1)) if key.startswith("~") else pm
        return self._pm[key]

    def get(self, name, default=None):
        name = ALIAS.get(name, name)
        if name not in ANIMS:
            return default
        fps, frames = ANIMS[name]
        return self._frame(frames[int(self.owner.t * fps) % len(frames)])

    __getitem__ = get


# --- painéis -------------------------------------------------------------------------------------------------

def fmt(n):
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}k"
    return str(int(n))


def fmt_duration(sec):
    m = int(sec // 60)
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m} min"


class UsagePanel(QWidget):
    """Cartão com o uso de tokens da sessão atual; fecha ao clicar fora."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setStyleSheet("color:#eee; font-size:10pt;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.addWidget(self.label)
        self.timer = QTimer(self, interval=USAGE_REFRESH_MS, timeout=self.refresh)
        self.closed_at = 0.0

    def refresh(self):
        data = usage.collect()
        if not data:
            self.label.setText("Nenhuma sessão encontrada em ~/.claude/projects")
            return
        s, w = data["session"], data["window"]
        total = s["input"] + s["output"] + s["cache_read"] + s["cache_write"]
        row = lambda k, v: f"<tr><td style='color:#aaa'>{k}&nbsp;&nbsp;</td><td align='right'>{v}</td></tr>"
        self.label.setText(
            "<div style='color:#d97757; font-weight:bold; font-size:11pt'>Sessão atual</div>"
            f"<div style='color:#aaa'>{data['model']}</div>"
            "<table cellspacing='2'>"
            + row("Mensagens", data["turns"])
            + row("Duração", fmt_duration(data["duration"]))
            + row("Entrada", fmt(s["input"]))
            + row("Saída", fmt(s["output"]))
            + row("Cache lido", fmt(s["cache_read"]))
            + row("Cache escrito", fmt(s["cache_write"]))
            + row("<b>Total</b>", f"<b>{fmt(total)}</b>")
            + row("Contexto agora", fmt(data["context"]))
            + "</table>"
            "<div style='color:#d97757; font-weight:bold; font-size:11pt; margin-top:6px'>Últimas 5h (todas as sessões)</div>"
            "<table cellspacing='2'>"
            + row("Mensagens", data["window_turns"])
            + row("Saída", fmt(w["output"]))
            + row("Entrada + cache escrito", fmt(w["input"] + w["cache_write"]))
            + row("Cache lido", fmt(w["cache_read"]))
            + "</table>"
        )
        self.adjustSize()

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
        p.setPen(QColor(217, 119, 87, 160))
        p.setBrush(QColor(32, 30, 34, 245))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)


MIC = ("..XXX..", ".XXXXX.", ".XXXXX.", ".XXXXX.", "X.XXX.X", "X.XXX.X", ".X...X.", "..XXX..", "...X...", "..XXX..")
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
        face = QColor(90, 230, 235) if key == "mic" else QColor(255, 190, 120)
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

    if key == "mic":
        bitmap(MIC, 3, 2, fg)
    elif key == "quit":
        bitmap(CROSS, 3, 3, fg)
    elif on:
        bitmap(SPK, 2, 3, fg)
    else:
        bitmap(SPK_OFF, 1, 3, fg)
        bitmap(CROSS, 5, 4, QColor(255, 110, 100))
    if on and key == "mic":  # ponto "ao vivo"
        cell(n - 4, 1, QColor(255, 80, 70) if int(t * 2) % 2 == 0 else QColor(255, 150, 140), 2, 2)
    p.restore()


class ToggleBar(QWidget):
    """Botões de microfone / som / sair, no topo do menu."""
    KEYS = ("mic", "speak", "quit")

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.hover = None
        self.setMouseTracking(True)
        self.setFixedSize(3 * 28 + 2 * 12, 30)
        QTimer(self, interval=250, timeout=self.update).start()

    def rects(self):
        return {k: QRectF(i * 40, 1, 28, 28) for i, k in enumerate(self.KEYS)}

    def at(self, pos):
        return next((k for k, r in self.rects().items() if r.contains(QPointF(pos))), None)

    def paintEvent(self, _):
        p = QPainter(self)
        o = self.owner
        for k, r in self.rects().items():
            on = o.voice_on if k == "mic" else o.speak_on if k == "speak" else True
            pixel_button(p, k, r, on, self.hover == k, o.t)

    def mouseMoveEvent(self, e):
        self.hover = self.at(e.position())
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


class MenuPanel(UsagePanel):
    """Menu do duplo clique: botões no topo e, abaixo, o uso de tokens."""

    def __init__(self, owner):
        super().__init__()
        self.layout().insertWidget(0, ToggleBar(owner), 0, Qt.AlignmentFlag.AlignHCenter)


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
        self.voice_on = VOICE_ON.exists()
        self.speak_on = not MUTE.exists()
        self.drag = None
        self.press_pos = None
        self.moved = False
        self.walk = None  # {"x", "alvo", "dir": +1/-1, "volta": x do canto, "pausa": até quando acena}
        self.next_walk = now + random.uniform(10, 20)
        self._wlast = now
        self._nome_ant = ""
        self._trans = None
        self.home = (0, 0)
        self.retorno = False  # interrompido longe do canto: volta deslizando
        self.panel = MenuPanel(self)
        self.apply_size()
        QTimer(self, interval=33, timeout=self.tick).start()
        self.place()

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

    def toggle(self, which):
        flag = VOICE_ON if which == "mic" else MUTE
        if flag.exists():
            flag.unlink(missing_ok=True)
        else:
            flag.touch()
        self.voice_on, self.speak_on = VOICE_ON.exists(), not MUTE.exists()

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
            self.voice_on = VOICE_ON.exists()  # acompanha também o `clawd-voz` e o comando "para de ouvir"
            self.speak_on = not MUTE.exists()
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
        self._walk_tick(now)
        if self.walk:  # andando: nada de variação de ócio por cima
            self.variant = ""
            self.next_variant = max(self.next_variant, now + 8)
        self.update()

    # --- passeio ---
    def _walk_tick(self, now):
        dt = min(0.1, now - self._wlast)
        self._wlast = now
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
        if self._trans and now < self._trans[1] and nome not in ("andar", "andar_esq", "acenar"):
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
        self.press_pos = e.globalPosition().toPoint()
        self.moved = False
        self.drag = self.press_pos - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            if (e.globalPosition().toPoint() - self.press_pos).manhattanLength() > 4:
                self.moved = True
            if self.moved:
                self.move(e.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, e):
        if self.drag is not None and not self.moved:  # um clique simples = carinho
            self.pet_until = time.monotonic() + 1.8
            self.happy_pick = random.choice(HAPPY_SPRITES)
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
