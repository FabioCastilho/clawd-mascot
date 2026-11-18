"""Fatia folhas 8x4 em fundo magenta (JPEG-ish, sem transparência) em quadros 160x125.
Tira o magenta por chave de cor com suavização na borda. Uso:
  python tools/montar_frente.py saida_dir prefixo=folha.png [prefixo=folha.png ...]
Gera {prefixo}{linha*8+coluna}.png. Escala e base únicas por pacote."""
import sys, pathlib
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
import os
COLS, ROWS, CW, CH, SCALE = 8, 4, 160, 125, 0.5
# Para casar com um pacote já feito: UNION_FRAC="x0,y0,x1,y1" (fração da célula) e ESCALA_CELULA (px de saída por célula)
UNION_FRAC = os.environ.get("UNION_FRAC")
ESCALA_CELULA = float(os.environ.get("ESCALA_CELULA", 0))

def chave(rgb):
    a = rgb.astype(float); R, G, B = a[..., 0], a[..., 1], a[..., 2]
    # distância ao magenta #FF00FF ponderada; magenta puro = fundo, rosa de coração tem B bem menor que R
    d = np.sqrt((255 - R) ** 2 + (G) ** 2 + (255 - B) ** 2)
    alpha = np.clip((d - 70) / 60, 0, 1)            # <70 fundo, >130 sólido
    out = np.dstack([rgb, (alpha * 255).astype(np.uint8)]).astype(np.uint8)
    # despill: tira o excesso de magenta (R e B altos, G baixo) dos pixels de borda
    edge = (alpha > 0) & (alpha < 1)
    spill = np.minimum(R, B) - G
    k = np.clip(spill / 255, 0, 1) * edge
    out[..., 0] = np.clip(R - (R - G) * k * 0.8, 0, 255)
    out[..., 2] = np.clip(B - (B - G) * k * 0.8, 0, 255)
    return out

def limpar(sub):
    """Tira o que o gerador deixa de sujeira: pontos magenta/rosa dentro do corpo e o contorno branco de 'adesivo'."""
    A = sub[..., 3].astype(np.uint8)
    corpo = ndi.binary_closing(A > 40, iterations=2)
    dentro = ndi.binary_fill_holes(corpo)
    R, G, B = (sub[..., i].astype(int) for i in range(3))
    # 1) buracos e pontinhos rosados pequenos dentro do corpo -> cor do vizinho, opacos
    rosa = (R > 190) & (B > 140) & (B - G > 35) & (R - G > 35) & (A > 0)
    lab, n = ndi.label(ndi.binary_dilation(rosa, iterations=1))
    ruim = (dentro & (A < 255))
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        comp = lab == i
        if (comp & rosa).sum() <= 14:
            ruim |= comp & rosa
    if ruim.any():
        ok = (A == 255) & ~ruim & ~rosa
        _, (iy, ix) = ndi.distance_transform_edt(~ok, return_indices=True)
        fill = sub[iy, ix]; sub[ruim] = fill[ruim]; sub[ruim, 3] = 255
    # 2) contorno branco/claro na borda externa (3 passadas = ~3 px)
    A = sub[..., 3]
    fora = ~ndi.binary_fill_holes(A > 40)
    claro = np.minimum(np.minimum(sub[..., 0], sub[..., 1]), sub[..., 2]) > 195
    for _ in range(3):
        borda = ndi.binary_dilation(fora) & ~fora & (A > 0)
        tirar = borda & claro
        if not tirar.any(): break
        sub[tirar] = 0; A = sub[..., 3]; fora = fora | tirar
    return sub


frames = []
for arg in sys.argv[2:]:
    pre, path = arg.split("=", 1)
    rgb = np.array(Image.open(path).convert("RGB")); H, W = rgb.shape[:2]
    rgba = chave(rgb)
    cw, ch = W / COLS, H / ROWS
    m = rgba[..., 3] > 40
    lab, n = ndi.label(ndi.binary_dilation(m, iterations=3))
    own = {}
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        if (m & (lab == i)).sum() < 25: continue
        cy, cx = (sl[0].start + sl[0].stop) / 2, (sl[1].start + sl[1].stop) / 2
        own[i] = (min(int(cy // ch), ROWS - 1), min(int(cx // cw), COLS - 1))
    for r in range(ROWS):
        for c in range(COLS):
            keep = np.isin(lab, [i for i, rc in own.items() if rc == (r, c)])
            y0, x0 = int(r * ch), int(c * cw)
            cell = np.zeros((int(ch), int(cw), 4), np.uint8)
            sub = rgba[y0:y0 + cell.shape[0], x0:x0 + cell.shape[1]].copy()
            k = keep[y0:y0 + cell.shape[0], x0:x0 + cell.shape[1]]
            sub[~k] = 0
            sub = limpar(sub)
            cell[:sub.shape[0], :sub.shape[1]] = sub
            frames.append((f"{pre}{r * COLS + c}", Image.fromarray(cell)))
bbs = [b for b in (f.getbbox() for _, f in frames) if b]
u = (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))
if UNION_FRAC:
    fx0, fy0, fx1, fy1 = map(float, UNION_FRAC.split(","))
    cwp, chp = frames[0][1].size
    u = (round(fx0 * cwp), round(fy0 * chp), round(fx1 * cwp), round(fy1 * chp))
if ESCALA_CELULA:
    SCALE = ESCALA_CELULA / frames[0][1].size[0]
for nome, f in frames:
    f = f.crop(u); f = f.resize((round(f.width * SCALE), round(f.height * SCALE)), Image.LANCZOS)
    cv = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    cv.paste(f, ((CW - f.width) // 2, CH - 4 - f.height), f)
    cv.save(OUT / f"{nome}.png")
print("ok", len(frames), u)
