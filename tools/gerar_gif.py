"""Gera o GIF-vitrine do README. Uso: python tools/gerar_gif.py [skin]
Sem argumento: docs/clawd.gif (sprites/). Com skin (ex.: luna): docs/<skin>.gif, usando skins/<skin>/ e sprites/ no que faltar."""
import os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
SKIN = sys.argv[1] if len(sys.argv) > 1 else ""
sys.path.insert(0, str(ROOT))
import clawd  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

MOSTRAR = [("neutral", "parado"), ("thinking", "pensando"), ("coding", "programando"),
           ("ler", "lendo"), ("comemorar", "testes ok"), ("acenar", "acenando"),
           ("andar", "passeando"), ("cafe", "café"), ("susto", "erro")]
COLS, CW, CH, LAB, FPS, SEG = 3, 160, 125, 22, 12, 4
BG = (30, 26, 43)
ROWS = -(-len(MOSTRAR) // COLS)
FONTE = ImageFont.load_default()
for f in ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
          "/usr/share/fonts/noto/NotoSans-Regular.ttf"):
    if Path(f).exists():
        FONTE = ImageFont.truetype(f, 13)
        break


def quadro(key):
    nome = f"{key.lstrip('~')}.png"
    p = ROOT / "skins" / SKIN / nome if SKIN else None
    im = Image.open(p if p and p.exists() else ROOT / "sprites" / nome).convert("RGBA")
    return im.transpose(Image.FLIP_LEFT_RIGHT) if key.startswith("~") else im


frames = []
for n in range(FPS * SEG):
    t = n / FPS
    img = Image.new("RGB", (COLS * CW, ROWS * (CH + LAB)), BG)
    d = ImageDraw.Draw(img)
    for i, (nome, rot) in enumerate(MOSTRAR):
        fps, qs = clawd.ANIMS[nome]
        q = quadro(qs[int(t * fps) % len(qs)])
        x, y = (i % COLS) * CW, (i // COLS) * (CH + LAB)
        img.paste(q, (x, y), q)
        d.text((x + CW // 2, y + CH + 3), rot, fill=(190, 180, 215), font=FONTE, anchor="mt")
    frames.append(img)
(ROOT / "docs").mkdir(exist_ok=True)
frames[0].save(ROOT / "docs" / f"{SKIN or 'clawd'}.gif", save_all=True, append_images=frames[1:],
               duration=1000 // FPS, loop=0, optimize=True)
print("ok", len(frames), "quadros")
