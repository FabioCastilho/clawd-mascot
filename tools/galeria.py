"""Gera galeria.html com todas as animações do Clawd (lê ANIMS de clawd.py). Uso: python tools/galeria.py"""
import json, os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import clawd  # noqa: E402

estados = {"neutral": "estado", "thinking": "estado", "coding": "estado", "alert": "estado", "listening": "estado", "sleep": "estado"}
felizes = set(clawd.HAPPY_SPRITES)
ocio = set(clawd.IDLE_VARIANTS)
dados = []
for nome, (fps, quadros) in clawd.ANIMS.items():
    grupo = "Estado" if nome in estados else ("Feliz" if nome in felizes else "Ócio")
    if nome in felizes and nome in ocio: grupo = "Feliz"
    dados.append({"nome": nome, "fps": fps, "grupo": grupo, "quadros": quadros})
html = """<!doctype html><html lang="pt-br"><meta charset="utf-8"><title>Clawd: ações</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#15121c;--card:#201b2c;--tx:#f1e9ff;--mut:#9c93b3;--ac:#ff9a3c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:#15121cee;backdrop-filter:blur(6px);padding:12px 16px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;border-bottom:1px solid #2e2840}
h1{font-size:18px;margin:0 8px 0 0}label{color:var(--mut);display:flex;gap:6px;align-items:center}
button,input{background:var(--card);color:var(--tx);border:1px solid #3a3350;border-radius:8px;padding:6px 10px;font:inherit}
button.on{background:var(--ac);color:#1a1208;border-color:var(--ac)}button{cursor:pointer}
main{padding:16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px}
h2{grid-column:1/-1;margin:14px 0 0;font-size:15px;color:var(--ac)}
.card{background:var(--card);border-radius:14px;padding:10px;text-align:center;border:1px solid #2e2840}
.card .tela{height:140px;display:flex;align-items:flex-end;justify-content:center;background:repeating-conic-gradient(#2a2438 0 25%,#241f31 0 50%) 0 0/16px 16px;border-radius:10px}
.card img{image-rendering:pixelated;height:125px;width:160px;object-fit:contain}
.card b{display:block;margin-top:8px}.card small{color:var(--mut)}
.card.sel{outline:2px solid var(--ac)}
</style>
<header><h1>Clawd: todas as ações</h1>
<span id="grupos"></span>
<label>velocidade <input id="vel" type="range" min="0.25" max="2" step="0.25" value="1"><span id="velv">1x</span></label>
<button id="pausa">Pausar</button><label>buscar <input id="q" placeholder="nome"></label><span id="cont" style="color:var(--mut)"></span></header>
<main id="m"></main>
<script>
const D=__DADOS__;let vel=1,pausa=false,filtro="Todos",q="";
const m=document.getElementById("m"),cards=[];
const ordem=["Estado","Feliz","Ócio"];
for(const g of ordem){const h=document.createElement("h2");h.textContent=g;h.dataset.g=g;m.appendChild(h);
 for(const a of D.filter(x=>x.grupo===g)){
  const c=document.createElement("div");c.className="card";c.dataset.g=g;c.dataset.n=a.nome;
  const t=document.createElement("div");t.className="tela";const im=document.createElement("img");t.appendChild(im);
  c.append(t);c.insertAdjacentHTML("beforeend",`<b>${a.nome}</b><small>${a.quadros.length} quadros · ${a.fps} fps</small>`);
  m.appendChild(c);cards.push({a,im,c,i:0,acc:0});
  c.onclick=()=>{c.classList.toggle("sel")};}}
const src=k=>"sprites/"+k.replace("~","")+".png";
const pre=new Set();D.forEach(a=>a.quadros.forEach(k=>{const i=new Image();i.src=src(k)}));
function pinta(o){const k=o.a.quadros[o.i%o.a.quadros.length];o.im.src=src(k);o.im.style.transform=k[0]==="~"?"scaleX(-1)":"none"}
cards.forEach(pinta);
let last=performance.now();
function loop(now){const dt=(now-last)/1000;last=now;
 if(!pausa)for(const o of cards){if(o.c.style.display==="none")continue;o.acc+=dt*o.a.fps*vel;
  while(o.acc>=1){o.acc-=1;o.i++;pinta(o)}}
 requestAnimationFrame(loop)}
requestAnimationFrame(loop);
function aplica(){let n=0;for(const o of cards){const ok=(filtro==="Todos"||o.a.grupo===filtro)&&o.a.nome.includes(q);o.c.style.display=ok?"":"none";if(ok)n++}
 document.querySelectorAll("h2").forEach(h=>{h.style.display=(filtro==="Todos"||h.dataset.g===filtro)?"":"none"});
 document.getElementById("cont").textContent=n+" ações"}
const gb=document.getElementById("grupos");
["Todos",...ordem].forEach(g=>{const b=document.createElement("button");b.textContent=g;if(g==="Todos")b.className="on";
 b.onclick=()=>{filtro=g;gb.querySelectorAll("button").forEach(x=>x.className="");b.className="on";aplica()};gb.appendChild(b)});
document.getElementById("vel").oninput=e=>{vel=+e.target.value;document.getElementById("velv").textContent=vel+"x"};
document.getElementById("pausa").onclick=e=>{pausa=!pausa;e.target.textContent=pausa?"Continuar":"Pausar"};
document.getElementById("q").oninput=e=>{q=e.target.value.toLowerCase();aplica()};
aplica();
</script></html>""".replace("__DADOS__", json.dumps(dados, ensure_ascii=False))
(ROOT / "galeria.html").write_text(html, encoding="utf-8")
print("galeria.html:", len(dados), "ações")
