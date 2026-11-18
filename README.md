# Clawd

Mascote de desktop em pixel art que reage ao [Claude Code](https://claude.com/claude-code).
Janela transparente, sempre no topo, feita com PyQt6.

## O que ele faz
- Mostra o que o Claude está fazendo: pensando, programando, lendo, buscando, testando, comemorando
  testes que passam, ficando triste quando falham, assustado com erros, alerta quando pede permissão.
- Parado, ele faz variações (ler, tomar café, acenar...), cochila e dorme, e passeia pela tela
  (acena no ponto mais distante e volta ao canto inferior direito).
- Clique = carinho · arrastar = mover · roda do mouse = tamanho · duplo clique = menu (microfone, som,
  uso de tokens, sair).

## Instalar
```bash
python -m venv .venv && .venv/bin/pip install PyQt6 python-xlib
.venv/bin/python clawd.py
```
`CLAWD_ANDAR=0` desliga o passeio; `CLAWD_VOICE=0` desliga a escuta por voz; `CLAWD_SPEAK=0` desliga a fala.
Linux (X11/XWayland). Para abrir no login, copie `clawd.desktop.example` para `~/.config/autostart/clawd.desktop`
e troque `CAMINHO`.

## Ligar ao Claude Code
Os hooks escrevem o estado em `$XDG_RUNTIME_DIR/clawd.state`. Copie `settings.example.json` para o bloco
`hooks` do seu `~/.claude/settings.json`, trocando `CAMINHO` pela pasta do projeto. `clawd-hook.py` lê o JSON
do hook e escolhe o estado pela ferramenta usada.

## Voz (opcional)
`voice.py` escuta o microfone (faster-whisper, offline) e `speak.py` fala ao fim de cada resposta (Piper ou
Kokoro). Os modelos vão em `voices/` (fora do git, são grandes). Instale as dependências extras do
`requirements.txt`.

## Sprites
Os quadros ficam em `sprites/` (`{folha}{n}.png`) e vêm de folhas 8x4 com fundo magenta:
```bash
python tools/montar_frente.py sprites c=costas.png d=direita_acoes.png ...
python tools/galeria.py     # gera galeria.html com todas as animações
```
As animações e o mapeamento estado → animação estão no topo de `clawd.py` (`ANIMS`, `STATE_SPRITE`).

## Créditos
Os sprites foram gerados com IA (ChatGPT, da OpenAI) e depois recortados e limpos com `tools/montar_frente.py`.

## Arquivos
| Arquivo | Função |
|---|---|
| `clawd.py` | o mascote (janela, animações, passeio, menu) |
| `clawd-hook.py` | hook do Claude Code: escolhe o estado |
| `usage.py` | uso de tokens lido de `~/.claude/projects` |
| `voice.py`, `speak.py`, `clawd-voz` | escuta e fala (opcionais) |
| `tools/` | recorte das folhas e galeria |
