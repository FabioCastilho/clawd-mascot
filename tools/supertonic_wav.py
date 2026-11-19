"""Gera um WAV com o Supertonic (roda no .venv-super). Uso: echo "texto" | .venv-super/bin/python tools/supertonic_wav.py F4 saida.wav"""
import sys
import soundfile as sf
from supertonic import TTS

voz, saida = sys.argv[1], sys.argv[2]
texto = sys.stdin.read().strip()
tts = TTS(model="supertonic-3", auto_download=True)
w, _ = tts.synthesize(texto, voice_style=tts.get_voice_style(voice_name=voz), lang="pt")
sf.write(saida, w.squeeze(), tts.sample_rate)
