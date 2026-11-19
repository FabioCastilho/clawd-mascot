"""Skins do Clawd.

Uma skin é uma pasta em skins/<nome>/ com um skin.json e, opcionalmente, PNGs próprios (mesmos nomes de sprites/,
ex.: f0.png). O que a skin não trouxer vem de sprites/ (a skin padrão), então uma skin pode ser parcial.

skin.json:
  {"nome": "Gelo",
   "recolorir": {"cabelo": 180, "capa": -50, "cabelo_sat": 0.8, "capa_sat": 1.0}}
`recolorir` troca as cores na hora, sem PNG: gira o matiz (em graus) do cabelo/detalhes (laranja) e da capa (roxo);
a pele clara não muda. `*_sat` multiplica a saturação (0 = cinza).
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

RAIZ = Path(__file__).resolve().parent
PADRAO = RAIZ / "sprites"
SKINS = RAIZ / "skins"


def recolorir(img, cabelo=0.0, capa=0.0, cabelo_sat=1.0, capa_sat=1.0):
    rgba = np.array(img.convert("RGBA"))
    alfa = rgba[..., 3]
    hsv = np.array(Image.fromarray(rgba[..., :3]).convert("HSV")).astype(float)
    h, s, v = hsv[..., 0] * 360 / 255, hsv[..., 1] / 255, hsv[..., 2] / 255
    quente = (h < 70) | (h > 340)
    roxo = (h >= 200) & (h <= 340) & (v > 0.12)
    detalhe = quente & (s > 0.5) & (v > 0.3)            # cabelo, emblema, brilhos; a pele clara (S baixo) fica de fora
    transicao = quente & (s > 0.4) & (s <= 0.5)         # sombra da pele junto ao cabelo
    novo_h, novo_s = h.copy(), s.copy()
    novo_h[detalhe] = (h[detalhe] + cabelo) % 360
    novo_s[detalhe] = np.clip(s[detalhe] * cabelo_sat, 0, 1)
    novo_h[transicao] = (h[transicao] + cabelo * 0.5) % 360
    novo_h[roxo] = (h[roxo] + capa) % 360
    novo_s[roxo] = np.clip(s[roxo] * capa_sat, 0, 1)
    hsv[..., 0], hsv[..., 1] = novo_h * 255 / 360, novo_s * 255
    rgb = np.array(Image.fromarray(hsv.astype("uint8"), "HSV").convert("RGB"))
    return Image.fromarray(np.dstack([rgb, alfa]), "RGBA")


def listar():
    """[(pasta, nome)]: a padrão primeiro, depois as de skins/ em ordem alfabética."""
    out = [("", "Clawd")]
    for d in sorted(p for p in SKINS.glob("*") if (p / "skin.json").exists()):
        try:
            nome = json.loads((d / "skin.json").read_text(encoding="utf-8")).get("nome", d.name.capitalize())
        except (OSError, ValueError):
            nome = d.name.capitalize()
        out.append((d.name, nome))
    return out


def receita(pasta):
    if not pasta:
        return {}
    try:
        return json.loads((SKINS / pasta / "skin.json").read_text(encoding="utf-8")).get("recolorir", {})
    except (OSError, ValueError):
        return {}


def quadro(chave, pasta):
    """Imagem PIL RGBA do quadro `chave` (ex.: "f0") na skin `pasta` ("" = padrão)."""
    if pasta:
        proprio = SKINS / pasta / f"{chave}.png"
        if proprio.exists():
            return Image.open(proprio).convert("RGBA")
    img = Image.open(PADRAO / f"{chave}.png").convert("RGBA")
    r = receita(pasta)
    return recolorir(img, **r) if r else img
