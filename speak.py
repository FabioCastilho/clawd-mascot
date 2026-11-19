#!/usr/bin/env python3
"""Clawd speaks a short summary of Claude's last reply (Claude Code Stop hook). Piper, offline, voz pt_BR masculina.

Hook: reads the hook JSON on stdin, forks, and returns immediately. Disable with CLAWD_SPEAK=0 or `touch ~/.clawd-mute`.
Writes the player's PID to $XDG_RUNTIME_DIR/clawd.speaking while talking (voice.py ignores the mic meanwhile).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_CUR = HERE / "voices" / "current"  # name of the chosen voice, e.g. pt_BR-faber-medium (change with `clawd-fala <nome>`)
NAME = _CUR.read_text().strip() if _CUR.exists() else "pt_BR-faber-medium"  # "supertonic:<voz>", "pocket:<voz>", "kokoro:<voz>" or a Piper voice name
MODEL = HERE / "voices" / f"{NAME}.onnx"
FLAG = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.speaking"
PTT = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.gravando"    # ditado por atalho gravando (ditado.py)
PENDENTE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.pendente"  # resposta que ficou sem ser falada
POCKET_PORT = int(os.environ.get("CLAWD_POCKET_PORT", "8765"))
SUPER_PY = HERE / ".venv-super" / "bin" / "python"
POCKET_BIN = HERE / ".venv-pocket" / "bin" / "pocket-tts"
MAX_CHARS = int(os.environ.get("CLAWD_SPEAK_CHARS", "220"))


def pocket_servidor(espera=60):
    """Garante o servidor do Pocket TTS no ar (o modelo fica na memória e responde em ~1 s). Devolve True se pronto."""
    import urllib.request

    def no_ar():
        try:
            return urllib.request.urlopen(f"http://127.0.0.1:{POCKET_PORT}/health", timeout=1).status == 200
        except OSError:
            return False

    if no_ar():
        return True
    if not POCKET_BIN.exists():
        return False
    voz = NAME.split(":", 1)[1] if ":" in NAME else "rafael"
    subprocess.Popen([str(POCKET_BIN), "serve", "--host", "127.0.0.1", "--port", str(POCKET_PORT),
                      "--language", "portuguese", "--default-voice", voz],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    fim = time.time() + espera
    while time.time() < fim:
        if no_ar():
            return True
        time.sleep(0.5)
    return False


def pocket_wav(text, wav):
    import urllib.parse
    import urllib.request
    if not pocket_servidor():
        return False
    req = urllib.request.Request(f"http://127.0.0.1:{POCKET_PORT}/tts", data=urllib.parse.urlencode({"text": text}).encode())
    with urllib.request.urlopen(req, timeout=120) as r, open(wav, "wb") as f:
        while chunk := r.read(65536):
            f.write(chunk)
    return os.path.getsize(wav) > 1000


def last_reply(data):
    if data.get("last_assistant_message"):
        return data["last_assistant_message"]
    path = data.get("transcript_path")
    for _ in range(5):  # the transcript may still be flushing
        text = ""
        try:
            for line in Path(path).read_text().splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") == "assistant":
                    parts = [c.get("text", "") for c in e.get("message", {}).get("content", []) if c.get("type") == "text"]
                    if parts:
                        text = "\n".join(parts)
        except (OSError, TypeError):
            return ""
        if text:
            return text
        time.sleep(0.3)
    return ""


def summarize(text):
    text = re.sub(r"```.*?```", ". ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s*\|.*$", " ", text, flags=re.M)  # tables
    text = re.sub(r"(?:~|\.{0,2})?/[\w./-]+", " ", text)  # paths
    text = re.sub(r"[#*_>|~\-]{1,}\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    out = ""
    for s in re.split(r"(?<=[.!?:])\s+", text):
        if out and len(out) + len(s) > MAX_CHARS:
            break
        out = f"{out} {s}".strip()
        if len(out) >= MAX_CHARS * 0.6:
            break
    return out[:MAX_CHARS + 60].strip()


def main():
    if os.environ.get("CLAWD_SPEAK") == "0" or (Path.home() / ".clawd-mute").exists():
        return
    pendente = "--pendente" in sys.argv  # chamado pelo ditado.py depois de você terminar de falar
    avulso = sys.argv[sys.argv.index("--texto") + 1] if "--texto" in sys.argv[:-1] else None  # fala uma frase pronta
    data = {}
    if avulso is not None and (PTT.exists() or FLAG.exists()):
        return  # você está gravando, ou ele já está falando: uma frase avulsa não atrapalha
    if not pendente and avulso is None:
        try:
            data = json.load(sys.stdin)
        except ValueError:
            data = {}
    if os.fork():
        return  # hook returns now
    os.setsid()
    if avulso is not None:
        text = avulso.strip()
    elif pendente:
        try:
            text = PENDENTE.read_text().strip()
            PENDENTE.unlink()
        except OSError:
            return
    else:
        text = summarize(last_reply(data))
        if text and PTT.exists():  # você está falando: não atrapalha, guarda para ler depois
            PENDENTE.write_text(text)
            return
        PENDENTE.unlink(missing_ok=True)  # resposta nova vale mais que a guardada
    if not text:
        return
    try:  # stop whatever is still talking
        os.kill(int(FLAG.read_text()), 15)
    except (OSError, ValueError):
        pass
    wav = tempfile.mktemp(suffix=".wav", prefix="clawd-")
    if NAME.startswith("pocket:"):  # e.g. "pocket:rafael" (Pocket TTS, servidor local em CPU)
        try:
            if not pocket_wav(text, wav):
                return
        except OSError:
            return
    elif NAME.startswith("supertonic:"):  # e.g. "supertonic:F4" (Supertonic 3, CPU, carrega em ~0,5 s)
        r = subprocess.run([str(SUPER_PY), str(HERE / "tools" / "supertonic_wav.py"), NAME.split(":", 1)[1], wav],
                           input=text.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0 or not os.path.exists(wav):
            return
    elif NAME.startswith("kokoro:"):  # e.g. "kokoro:pm_alex"
        import soundfile as sf
        from kokoro_onnx import Kokoro

        k = Kokoro(str(HERE / "voices/kokoro/kokoro-v1.0.onnx"), str(HERE / "voices/kokoro/voices-v1.0.bin"))
        audio, sr = k.create(text, voice=NAME.split(":", 1)[1], speed=1.0, lang="pt-br")
        sf.write(wav, audio, sr)
    else:
        subprocess.run([sys.executable, "-m", "piper", "-m", str(MODEL), "-f", wav], input=text.encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p = subprocess.Popen(["paplay", wav])
    FLAG.write_text(str(p.pid))
    p.wait()
    try:
        FLAG.unlink()
        os.unlink(wav)
    except OSError:
        pass


if __name__ == "__main__":
    main()
