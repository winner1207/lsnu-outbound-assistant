# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ENV = ROOT / ".deploy.env"


def load_deploy_env() -> dict[str, str]:
    data: dict[str, str] = {}
    if DEPLOY_ENV.exists():
        for raw in DEPLOY_ENV.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip("'\"")
    for key in ("DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_PASS", "DEPLOY_PATH", "DEPLOY_KEY"):
        if os.environ.get(key):
            data[key] = os.environ[key]
    missing = [k for k in ("DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_PATH") if not data.get(k)]
    if missing:
        raise SystemExit(f"缺少 {missing}，请写在 .deploy.env 或环境变量")
    if not data.get("DEPLOY_PASS") and not data.get("DEPLOY_KEY"):
        raise SystemExit("需要 DEPLOY_KEY 或 DEPLOY_PASS")
    return data


def ensure_ssh_key(client: paramiko.SSHClient) -> None:
    pub = Path.home() / ".ssh" / "id_ed25519.pub"
    if not pub.exists():
        print("SKIP ssh key: no ~/.ssh/id_ed25519.pub")
        return
    key = pub.read_text(encoding="utf-8").strip()
    cmd = (
        "umask 077; mkdir -p /root/.ssh; "
        "touch /root/.ssh/authorized_keys; "
        f"grep -qxF '{key}' /root/.ssh/authorized_keys || echo '{key}' >> /root/.ssh/authorized_keys; "
        "chmod 700 /root/.ssh; chmod 600 /root/.ssh/authorized_keys"
    )
    _, stdout, stderr = client.exec_command(cmd, timeout=15)
    stdout.read()
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        print("ssh-key stderr:", err)
    else:
        print("authorized_keys: local ed25519 pub appended if missing")


def remote_run(client: paramiko.SSHClient, cmd: str, timeout: int = 120) -> int:
    print("\n$ " + cmd)
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("[stderr]", err.rstrip())
    print("exit", code)
    return code


def main() -> int:
    cfg = load_deploy_env()
    host, user, dest = cfg["DEPLOY_HOST"], cfg["DEPLOY_USER"], cfg["DEPLOY_PATH"]
    password = cfg.get("DEPLOY_PASS") or None
    key_path = cfg.get("DEPLOY_KEY") or None
    print(f"deploy {host}:{dest} as {user} (git pull)")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kw = {
        "hostname": host,
        "username": user,
        "timeout": 20,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if key_path:
        connect_kw["key_filename"] = str(Path(key_path).expanduser())
    if password:
        connect_kw["password"] = password
    client.connect(**connect_kw)
    ensure_ssh_key(client)

    if remote_run(client, f"test -d {dest}/.git") != 0:
        print(f"{dest} 还不是 git 仓库。生产应先 HTTPS clone：")
        print("  git clone --branch main https://github.com/winner1207/lsnu-outbound-assistant.git " + dest)
        client.close()
        return 1

    code = remote_run(client, f"bash {dest}/deploy/git_pull.sh", timeout=600)
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
