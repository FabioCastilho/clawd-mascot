#!/usr/bin/env python3
"""Voice dictation for Clawd: say his name, then speak, and the text is typed into your Konsole session.

Flow (all local/offline, faster-whisper):
  mic -> energy VAD segments -> whisper -> wake word "Clawd" -> dictation -> Konsole `sendText` over DBus

- "Clawd, <frase>"        -> types <frase> in the Claude Code session (no Enter)
- "Clawd" (pause) <frase> -> he perks up, the next thing you say is typed
- "Clawd enviar" / "Clawd enter" -> presses Enter
- "Clawd apagar" / "limpar"      -> clears the input line (Ctrl+U)
- "Clawd mudo" / "Clawd volta"   -> mutes / unmutes the microphone processing

Use: `from voice import attach; attach(clawd_widget)` (done by clawd.py). Disable with CLAWD_VOICE=0.
Env: CLAWD_VOICE_MODEL (default "small"), CLAWD_VOICE_LANG (default "pt"), CLAWD_VOICE_DEVICE (sounddevice name/index).
Needs the project venv: .venv/bin/python clawd10.py
"""
import os
import queue
import re
import subprocess
import threading
import time
import unicodedata
from pathlib import Path

import numpy as np

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

ENABLED = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.voice-on"  # created by `clawd-voz on`
SPEAKING = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.speaking"
PENDENTE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.pendente"  # resposta guardada enquanto você grava
PTT = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.gravando"  # ditado por atalho (ditado.py) em andamento
RATE = 16000
BLOCK = 512  # 32 ms
MIN_SEG = 0.35  # seconds of speech needed to bother transcribing
END_SILENCE = 0.8
MAX_SEG = 15.0
SESSION_TIMEOUT = 25.0  # conversation mode: seconds of quiet before he needs "Clawd" again
CMD_BYE = {"tchau", "encerrar", "encerra", "chega", "pode parar", "para", "parar", "fim", "valeu", "obrigado", "so isso", "e so isso"}
CMD_OFF = {"para de ouvir", "pare de ouvir", "parar de ouvir", "desligar", "desliga", "desativar", "desativa", "desligar voz", "desligar microfone"}
PRE_ROLL = 0.25

WAKE = re.compile(r"\b(cl[aoeu]+w?u?d[eiao]?|clod|clode|claudi|claudio|cloude)\b[\s,.:;!?-]*", re.I)
CMD_ENTER = {"enviar", "envia", "enviou", "eviar", "evia", "enviare", "enviar a", "inviar", "enter", "manda", "mandar"}
CMD_CLEAR = {"apagar", "apaga", "limpar", "limpa", "cancelar"}
CMD_MUTE = {"mudo", "silencio", "silencio.", "pausar"}
CMD_UNMUTE = {"volta", "voltar", "ouvir", "escutar"}
JUNK = {"", "obrigado", "tchau", "legendas pela comunidade amara.org", "e ai", "e ai."}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s).strip()


# ---------- Modelo do whisper (compartilhado com o ditado por atalho) -----------------------------------------------

MODEL_LOCK = threading.Lock()
_MODEL = None


def get_model():
    global _MODEL
    with MODEL_LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel

            _MODEL = WhisperModel(os.environ.get("CLAWD_VOICE_MODEL", "small"), device="cpu", compute_type="int8")
        return _MODEL


# ---------- Konsole -------------------------------------------------------------------------------------------------

def _q(*args):
    try:
        return subprocess.run(["qdbus6", *args], capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return ""


def find_session():
    """(service, session path) of the Konsole tab running claude. Prefers the tab you are looking at (the window's
    current session); otherwise the newest claude tab; otherwise any tab."""
    fallback, claudes, visible = None, [], set()
    for svc in re.findall(r"org\.kde\.konsole-\d+", _q()):
        for win in re.findall(r"^/Windows/\d+", _q(svc), re.M):
            cur = _q(svc, win, "currentSession").strip()
            if cur:
                visible.add((svc, f"/Sessions/{cur}"))
        for path in re.findall(r"^/Sessions/\d+", _q(svc), re.M):
            fallback = fallback or (svc, path)
            pid = _q(svc, path, "foregroundProcessId").strip()
            try:
                comm = open(f"/proc/{pid}/comm").read().strip()
            except OSError:
                continue
            if comm in ("claude", "node"):
                claudes.append((svc, path))
    for t in claudes:
        if t in visible:
            return t
    return claudes[-1] if claudes else fallback


def send_text(text):
    target = find_session()
    if not target:
        print("[voice] nenhum Konsole encontrado")
        return False
    r = subprocess.run(["qdbus6", target[0], target[1], "sendText", text], capture_output=True, text=True, timeout=3)
    if r.returncode:
        print("[voice] Konsole recusou o sendText:", (r.stdout + r.stderr).strip().splitlines()[-1:], flush=True)
        return False
    return True


# ---------- Voice engine --------------------------------------------------------------------------------------------

class Voice(QObject):
    state = pyqtSignal(str)
    arm = pyqtSignal()

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.state.connect(self._set_state)
        self.arm.connect(self.arm_end)
        self.q = queue.Queue()
        self.muted = False
        self.session_until = 0.0
        self.ended = False
        self.last_session = 0.0
        self.was_speaking = False
        threading.Thread(target=self.run, daemon=True).start()

    def _set_state(self, name):
        if name == "end":  # conversation over: back to idle, but only if nothing else took over the mascot
            if self.widget.state == "listening":
                self.widget.set_state("idle")
            return
        if name == "listening" and hasattr(self.widget, "wake"):
            self.widget.wake()
        self.widget.set_state(name)
        if name in ("happy", "alert"):
            QTimer.singleShot(1800, lambda: self.widget.state == name and self.widget.set_state("idle"))

    def log(self, *a):
        print("[voice]", *a, flush=True)

    # --- audio

    def segments(self):
        """Yield (float32 speech segment, start time), split by silence. The mic is open only while ENABLED exists."""
        import sounddevice as sd

        dev = os.environ.get("CLAWD_VOICE_DEVICE")
        if dev and dev.isdigit():
            dev = int(dev)
        stream = None
        floor, buf, speech, silent, t0 = 0.01, [], False, 0.0, 0.0
        pre = []
        while True:
            if not ENABLED.exists():
                if stream:
                    stream.stop()
                    stream.close()
                    stream = None
                    self.log("microfone desligado")
                speech, buf = False, []
                time.sleep(0.5)
                continue
            if not stream:
                self.q = queue.Queue()
                stream = sd.InputStream(samplerate=RATE, channels=1, blocksize=BLOCK, dtype="float32", device=dev or None,
                                        callback=lambda d, *_: self.q.put(d[:, 0].copy()))
                stream.start()
                self.log("ouvindo… diga 'Clawd'")
            try:
                blk = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if SPEAKING.exists() or PTT.exists():  # Clawd is talking / ditado por atalho gravando: don't hear it
                speech, buf, silent, self.was_speaking = False, [], 0.0, True
                continue
            if self.was_speaking:  # he just finished a spoken reply: keep the conversation going without his name
                self.was_speaking = False
                if time.monotonic() - self.last_session < 600:
                    self.open_session()
                    self.log("resposta falada; pode continuar")
            rms = float(np.sqrt(np.mean(blk * blk)))
            loud = rms > max(0.015, floor * 3.0)
            if not speech:
                floor = floor * 0.95 + rms * 0.05
                pre = (pre + [blk])[-int(PRE_ROLL * RATE / BLOCK):]
                if loud:
                    speech, buf, silent, t0 = True, list(pre), 0.0, time.monotonic()
                    buf.append(blk)
                continue
            buf.append(blk)
            silent = 0.0 if loud else silent + BLOCK / RATE
            dur = len(buf) * BLOCK / RATE
            if silent >= END_SILENCE or dur >= MAX_SEG:
                speech = False
                if dur - silent >= MIN_SEG:
                    yield np.concatenate(buf), t0
                buf = []

    def transcribe(self, model, audio):
        with MODEL_LOCK:
            segs, _ = model.transcribe(audio, language=os.environ.get("CLAWD_VOICE_LANG", "pt"), beam_size=1,
                                       vad_filter=False, condition_on_previous_text=False,
                                       initial_prompt="Clawd, Claude Code, terminal, Python, git.")
            segs = list(segs)
        return " ".join(s.text.strip() for s in segs).strip()

    # --- logic

    def run(self):
        model = None
        try:
            for audio, t0 in self.segments():
                if model is None:
                    try:
                        model = get_model()
                    except Exception as e:  # noqa: BLE001
                        self.log("faltam dependências (rode com .venv/bin/python):", e)
                        return
                in_session = t0 < self.session_until  # he was already "all ears" when you started speaking
                text = self.transcribe(model, audio)
                self.log("ouvi:", repr(text))
                m = WAKE.match(text) if in_session else WAKE.search(text)
                if not in_session and not m:
                    continue
                rest = text[m.end():].strip() if m else text.strip()
                if not rest:  # just his name: open the conversation
                    self.open_session()
                    self.log("sim? (conversa aberta)")
                    continue
                self.ended = False
                rest, send = self.split_send(rest)  # "…frase. Enviar." => type the phrase, then press Enter
                if rest and not self.command(rest):
                    self.dictate(rest)
                if send:
                    send_text("\r")
                    self.log("enviado (Enter)")
                if not self.ended:
                    self.open_session()  # every exchange extends the conversation
        except Exception as e:  # noqa: BLE001
            self.log("erro no microfone:", e)

    @staticmethod
    def split_send(text):
        """Strip trailing send-words ("enviar", "eviar"…) from the phrase; True if any was there."""
        words, send = text.split(), False
        while words and norm(words[-1]) in CMD_ENTER:
            words.pop()
            send = True
        return " ".join(words), send

    def open_session(self):
        """Conversation mode: no need to repeat the wake word until SESSION_TIMEOUT seconds of quiet."""
        self.session_until = time.monotonic() + SESSION_TIMEOUT
        self.last_session = time.monotonic()
        self.state.emit("listening")
        self.arm.emit()

    def arm_end(self):  # main thread: poll until the session lapses
        if not hasattr(self, "_end_timer"):
            self._end_timer = QTimer(self)
            self._end_timer.timeout.connect(self.check_end)
        self._end_timer.start(500)

    def check_end(self):
        if time.monotonic() >= self.session_until and not SPEAKING.exists():
            self._end_timer.stop()
            self._set_state("end")

    def close_session(self):
        self.ended = True
        self.session_until = 0.0
        self.state.emit("end")

    def command(self, rest):
        w = norm(rest)
        if w in CMD_UNMUTE:
            self.muted = False
            self.state.emit("happy")
            return True
        if self.muted:
            return True
        if w in CMD_MUTE:
            self.muted = True
            self.state.emit("idle")
            self.log("mudo")
            return True
        if w in CMD_OFF or w.endswith(("para de ouvir", "pare de ouvir")):
            try:
                ENABLED.unlink()  # closes the microphone completely, like `clawd-voz off`
            except OSError:
                pass
            self.close_session()
            self.log("voz desligada por comando")
            return True
        if w in CMD_BYE or w.endswith(" tchau"):
            self.close_session()
            self.log("conversa encerrada")
            return True
        if w in CMD_ENTER:
            send_text("\r")
            self.state.emit("happy")
            return True
        if w in CMD_CLEAR:
            send_text("\x15")
            self.state.emit("happy")
            return True
        return False

    def dictate(self, text):
        text = text.strip()
        if self.muted or norm(text) in JUNK:
            return
        if self.command(text):
            return
        if send_text(text + " "):
            self.log("digitado:", text)
            self.state.emit("happy")


def attach(widget):
    if os.environ.get("CLAWD_VOICE", "1") == "0":
        return None
    widget._voice = Voice(widget)  # keep a reference
    return widget._voice
