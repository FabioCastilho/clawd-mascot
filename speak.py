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
NAME = _CUR.read_text().strip() if _CUR.exists() else "pt_BR-faber-medium"  # "kokoro:<voz>" or a Piper voice name
MODEL = HERE / "voices" / f"{NAME}.onnx"
FLAG = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "clawd.speaking"
MAX_CHARS = int(os.environ.get("CLAWD_SPEAK_CHARS", "220"))


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
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    if os.fork():
        return  # hook returns now
    os.setsid()
    text = summarize(last_reply(data))
    if not text:
        return
    try:  # stop whatever is still talking
        os.kill(int(FLAG.read_text()), 15)
    except (OSError, ValueError):
        pass
    wav = tempfile.mktemp(suffix=".wav", prefix="clawd-")
    if NAME.startswith("kokoro:"):  # e.g. "kokoro:pm_alex"
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
