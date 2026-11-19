"""Gera um WAV com o Supertonic (roda no .venv-super).
Uso: echo "texto" | .venv-super/bin/python tools/supertonic_wav.py F2 saida.wav [passos] [velocidade]"""
import os
import sys
import soundfile as sf
from supertonic import TTS

voz, saida = sys.argv[1], sys.argv[2]
passos = int(sys.argv[3]) if len(sys.argv) > 3 else int(os.environ.get("CLAWD_SUPERTONIC_PASSOS", 16))
vel = float(sys.argv[4]) if len(sys.argv) > 4 else float(os.environ.get("CLAWD_SUPERTONIC_VELOCIDADE", 1.05))
texto = sys.stdin.read().strip()
tts = TTS(model="supertonic-3", auto_download=True)
w, _ = tts.synthesize(texto, voice_style=tts.get_voice_style(voice_name=voz), lang="pt", total_steps=passos, speed=vel)
sf.write(saida, w.squeeze(), tts.sample_rate)
