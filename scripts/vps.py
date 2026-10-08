"""Управление боем на VPS по SSH (см. docs/vps.md). Секреты — в .vps/secrets.env (не в git).

    python scripts/vps.py status              состояние сервиса, активный бот, релиз, права на теги
    python scripts/vps.py deploy              выложить текущий origin-ветку (fork/main) новым релизом и перезапустить
    python scripts/vps.py rollback            вернуть предыдущий релиз (из override.conf.prev)
    python scripts/vps.py switch-bot kei|dota2chattrack   сменить BOT_TOKEN в /etc/dota-party-tracker.env
    python scripts/vps.py logs [N]            последние N строк журнала (по умолчанию 40)

Нужен paramiko (pip install paramiko). Таро-бот (shepot-*) скрипт не трогает.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".vps" / "secrets.env"
REPO = "https://github.com/adxptived/dota-party-tracker"
BASE = "/opt/dota-party-tracker"
SERVICE = "dota-party-tracker"
OVERRIDE = f"/etc/systemd/system/{SERVICE}.service.d/override.conf"
ENV_FILE = "/etc/dota-party-tracker.env"
BOTS = {"kei": "BOT_TOKEN_KEI", "dota2chattrack": "BOT_TOKEN_DOTA2CHATTRACK"}


def load_secrets() -> dict[str, str]:
    if not SECRETS.exists():
        sys.exit(f"Нет {SECRETS} — создайте по образцу из docs/vps.md")
    out = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if re.match(r"^[A-Z0-9_]+=", line):
            key, _, value = line.partition("=")
            out[key] = value.strip()
    return out


def connect(sec: dict[str, str]) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for _ in range(3):  # sshd иногда рвёт первое рукопожатие
        try:
            client.connect(sec["VPS_HOST"], int(sec.get("VPS_PORT", 22)), sec["VPS_USER"], sec["VPS_PASSWORD"], timeout=20)
            return client
        except paramiko.SSHException:
            time.sleep(3)
    sys.exit("SSH не подключается")


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 300, check: bool = True) -> str:
    _, out, err = client.exec_command(cmd, timeout=timeout)
    text = out.read().decode(errors="replace")
    code = out.channel.recv_exit_status()
    if check and code:
        sys.exit(f"Ошибка ({code}): {cmd[:80]}\n{err.read().decode(errors='replace')}")
    return text.strip()


def bot_username(client, token_var: str = "BOT_TOKEN") -> str:
    return run(client, f"""set -a; . {ENV_FILE}; set +a; curl -s https://api.telegram.org/bot$BOT_TOKEN/getMe | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['username'])" """, check=False)


def status(client) -> None:
    print("сервис:", run(client, f"systemctl is-active {SERVICE}", check=False))
    print("активный бот: @" + bot_username(client))
    print("релиз:", run(client, f"grep WorkingDirectory {OVERRIDE}"))
    print("релизы:", run(client, f"ls -d {BASE}/release-* | xargs -n1 basename | tr '\\n' ' '"))
    print("ресурсы:", run(client, f"ps -o pcpu,rss,etime -p $(systemctl show -p MainPID --value {SERVICE}) | tail -1"))
    print("ошибки за 10 мин:", run(client, f"journalctl -u {SERVICE} --since '-10min' --no-pager | grep -cE 'ERROR|Traceback'", check=False))
    print("таро-бот:", run(client, "systemctl is-active shepot-tarot shepot-autopost shepot-support | tr '\\n' ' '", check=False))


def restart_and_check(client) -> None:
    run(client, f"systemctl daemon-reload && systemctl restart {SERVICE}")
    time.sleep(15)
    state = run(client, f"systemctl is-active {SERVICE}", check=False)
    log = run(client, f"journalctl -u {SERVICE} --since '-15s' --no-pager | grep -E 'Run polling|Conflict' | cut -c1-200", check=False)
    print("сервис:", state)
    print(log)
    if state != "active" or "Conflict" in log:
        print("!!! проблема: проверьте логи (python scripts/vps.py logs) или откатитесь (rollback)")


def deploy(client) -> None:
    stamp = time.strftime("%Y%m%d-%H%M")
    rel, venv = f"{BASE}/release-{stamp}", f"{BASE}/venv-{stamp}"
    current_py = run(client, f"readlink -f $(ls -d {BASE}/venv-*/ | tail -1)bin/python")
    run(client, f"git clone -q --depth 1 {REPO} {rel}")
    print("клонировано:", run(client, f"cd {rel} && git log --oneline -1 | cut -c1-80"))
    run(client, f"{current_py} -m venv {venv} && {venv}/bin/pip install -q -r {rel}/requirements.txt", timeout=600)
    run(client, f"cd {rel} && PYTHONDONTWRITEBYTECODE=1 {venv}/bin/python -c 'import mmrbot.__main__'")  # импорт-проверка до переключения
    run(client, f"chown -R dota-party:dota-party {rel} && chmod -R o-rwx {rel}")
    run(client, f"""python3 -c "import sqlite3;s=sqlite3.connect('file:/var/lib/dota-party-tracker/mmrbot.db?mode=ro',uri=True);d=sqlite3.connect('{BASE}/predeploy-{stamp}.db');s.backup(d);d.close()" && chmod 600 {BASE}/predeploy-{stamp}.db""")
    run(client, f"cp -p {OVERRIDE} {OVERRIDE}.prev && printf '[Service]\\nWorkingDirectory={rel}\\nExecStart=\\nExecStart={venv}/bin/python -m mmrbot\\n' > {OVERRIDE}")
    restart_and_check(client)


def rollback(client) -> None:
    run(client, f"test -f {OVERRIDE}.prev && cp -p {OVERRIDE}.prev {OVERRIDE}")
    restart_and_check(client)


def switch_bot(client, sec, name: str) -> None:
    token = sec.get(BOTS[name])
    if not token:
        sys.exit(f"В secrets.env нет {BOTS[name]}")
    sftp = client.open_sftp()
    lines = sftp.open(ENV_FILE).read().decode().splitlines()
    lines = [f"BOT_TOKEN={token}" if line.startswith("BOT_TOKEN=") else line for line in lines]
    with sftp.open("/tmp/dpt.env.new", "w") as f:
        f.write("\n".join(lines) + "\n")
    run(client, f"cp -p {ENV_FILE} {BASE}/env-before-switch.bak && install -m 600 -o root -g root /tmp/dpt.env.new {ENV_FILE} && rm /tmp/dpt.env.new")
    restart_and_check(client)
    print("активный бот: @" + bot_username(client))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows иначе ломает кириллицу
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    sec = load_secrets()
    client = connect(sec)
    if cmd == "status":
        status(client)
    elif cmd == "deploy":
        deploy(client)
    elif cmd == "rollback":
        rollback(client)
    elif cmd == "switch-bot" and len(sys.argv) > 2 and sys.argv[2] in BOTS:
        switch_bot(client, sec, sys.argv[2])
    elif cmd == "logs":
        print(run(client, f"journalctl -u {SERVICE} -n {int(sys.argv[2]) if len(sys.argv) > 2 else 40} --no-pager -o cat | cut -c1-240"))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
