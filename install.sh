#!/bin/sh
# Instala o Clawd: cria o .venv, instala as dependências e liga os hooks do Claude Code.
#   ./install.sh               mascote + hooks + autostart
#   ./install.sh --voz         também escuta/fala/ditado (baixa dependências grandes) e o atalho Ctrl+Alt+Espaço
#   ./install.sh --desinstalar tira hooks, autostart e atalho (a pasta fica)
# Outras opções vão direto para tools/instalar.py (--sem-autostart, --dry-run).
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "precisa do python3"; exit 1; }
VOZ=0; for a in "$@"; do [ "$a" = "--voz" ] && VOZ=1; [ "$a" = "--desinstalar" ] && exec python3 tools/instalar.py "$@"; done
if [ ! -x .venv/bin/python ]; then echo "→ criando .venv"; python3 -m venv .venv; fi
echo "→ instalando dependências"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q PyQt6 Pillow numpy python-xlib
if [ "$VOZ" = 1 ]; then
  echo "→ dependências de voz (pode demorar)"
  .venv/bin/pip install -q sounddevice faster-whisper piper-tts kokoro-onnx soundfile
  echo "  Os modelos de voz da fala (Piper/Kokoro) vão em voices/; veja o README. O ditado baixa o whisper sozinho."
fi
chmod +x clawd-voz clawd-hook.py clawd-statusline.py 2>/dev/null || true
echo "→ configurando o Claude Code"
.venv/bin/python tools/instalar.py "$@"
