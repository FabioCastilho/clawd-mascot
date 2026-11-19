"""Configura o Clawd na máquina: hooks e statusLine do Claude Code, autostart e (com --voz) o atalho do ditado.
Chamado por install.sh; pode rodar sozinho:  python tools/instalar.py [--voz] [--sem-autostart] [--dry-run] [--desinstalar]
Mexe só no que é do Clawd, faz backup de ~/.claude/settings.json antes e não sobrescreve um statusLine alheio."""
import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HOME = Path.home()
SETTINGS = HOME / ".claude" / "settings.json"
AUTOSTART = HOME / ".config" / "autostart" / "clawd-mascot.desktop"
ATALHO_DESKTOP = HOME / ".local" / "share" / "applications" / "clawd-gravar.desktop"
EVENTOS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Notification", "Stop"]


def nosso(cmd):
    return "clawd-hook.py" in cmd or "clawd-statusline.py" in cmd or str(RAIZ / "speak.py") in cmd


def carregar():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def salvar(cfg, dry):
    if dry:
        print("  (dry-run) escreveria", SETTINGS)
        return
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS.exists():
        bak = SETTINGS.with_name(f"settings.json.bak-clawd-{int(time.time())}")
        shutil.copy2(SETTINGS, bak)
        print("  backup:", bak)
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, SETTINGS)


def limpar(cfg):
    """Tira do settings tudo que é do Clawd (hooks e statusLine)."""
    hooks = cfg.get("hooks", {})
    for ev in list(hooks):
        grupos = []
        for g in hooks[ev]:
            g["hooks"] = [h for h in g.get("hooks", []) if not nosso(h.get("command", ""))]
            if g["hooks"]:
                grupos.append(g)
        if grupos:
            hooks[ev] = grupos
        else:
            del hooks[ev]
    if not hooks:
        cfg.pop("hooks", None)
    if nosso(cfg.get("statusLine", {}).get("command", "")):
        del cfg["statusLine"]


def instalar_hooks(cfg, voz):
    py = shutil.which("python3") or sys.executable
    venv = RAIZ / ".venv" / "bin" / "python"
    hooks = cfg.setdefault("hooks", {})
    for ev in EVENTOS:
        lista = hooks.setdefault(ev, [])
        cmds = [{"type": "command", "command": f'{py} "{RAIZ / "clawd-hook.py"}" {ev}'}]
        if ev == "Stop" and voz:
            cmds.append({"type": "command", "command": f'"{venv}" "{RAIZ / "speak.py"}"'})
        lista.append({"hooks": cmds})
    sl = cfg.get("statusLine")
    if sl and not nosso(sl.get("command", "")):
        print("  AVISO: você já tem um statusLine; não mexi. Para as barras de limite no menu, chame")
        print(f'         {RAIZ / "clawd-statusline.py"} a partir do seu (ele guarda os limites e não imprime nada).')
    else:
        cfg["statusLine"] = {"type": "command", "command": f'{py} "{RAIZ / "clawd-statusline.py"}"'}


def escrever(path, texto, dry):
    if dry:
        print("  (dry-run) escreveria", path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto, encoding="utf-8")


def autostart(dry):
    venv = RAIZ / ".venv" / "bin" / "python"
    escrever(AUTOSTART, f"[Desktop Entry]\nType=Application\nName=Clawd\nExec={venv} {RAIZ / 'clawd.py'}\n"
                        f"Path={RAIZ}\nTerminal=false\n", dry)
    print("  autostart:", AUTOSTART)


def atalho(dry):
    escrever(ATALHO_DESKTOP, "[Desktop Entry]\nType=Application\nName=Clawd: gravar / enviar ditado\n"
                             f"Exec={RAIZ / 'clawd-voz'} gravar\nIcon=audio-input-microphone\nNoDisplay=true\n"
                             "Terminal=false\nX-KDE-GlobalAccel-CommandShortcut=true\n", dry)
    kw = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if not kw:
        print("  atalho do ditado: não é KDE? Crie você um atalho que rode:", RAIZ / "clawd-voz", "gravar")
        return
    if not dry:
        subprocess.run([kw, "--file", "kglobalshortcutsrc", "--group", "services", "--group", "clawd-gravar.desktop",
                        "--key", "_launch", "Ctrl+Alt+Space"], check=False)
    print("  atalho do ditado: Ctrl+Alt+Espaço (vale depois de reiniciar a sessão ou de abrir Configurações → Atalhos)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voz", action="store_true", help="liga a fala ao fim de cada resposta e cria o atalho do ditado")
    ap.add_argument("--sem-autostart", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--desinstalar", action="store_true")
    a = ap.parse_args()
    cfg = carregar()
    if a.desinstalar:
        limpar(cfg)
        salvar(cfg, a.dry_run)
        for f in (AUTOSTART, ATALHO_DESKTOP):
            if f.exists() and not a.dry_run:
                f.unlink()
        print("Clawd removido dos hooks, do autostart e do atalho (a pasta do projeto fica).")
        return
    print("Claude Code:", SETTINGS)
    limpar(cfg)  # refazer = idempotente
    instalar_hooks(cfg, a.voz)
    salvar(cfg, a.dry_run)
    if not a.sem_autostart:
        autostart(a.dry_run)
    if a.voz:
        atalho(a.dry_run)
    print("Pronto. Rode:", RAIZ / ".venv" / "bin" / "python", RAIZ / "clawd.py")


main()
