# -*- coding: utf-8 -*-
"""把本仓库同步到部署机 /opt/lsnu-outbound-assistant。密钥或密码只从 .deploy.env 读。"""
from __future__ import annotations

import os
import posixpath
import stat
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ENV = ROOT / ".deploy.env"
SKIP_DIRS = {".git", ".venv", "__pycache__", ".ssh"}
SKIP_FILES = {".deploy.env"}
SKIP_NAME_PREFIX = ("_probe_host", "_switch_host", "_patch_")


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


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    if path.name in SKIP_FILES:
        return True
    if path.name.startswith(SKIP_NAME_PREFIX):
        return True
    return False


def iter_local_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path):
            continue
        yield path


def sftp_mkdirs(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    parts = []
    current = ""
    for part in remote_dir.strip("/").split("/"):
        current = current + "/" + part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


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
    print(f"deploy {host}:{dest} as {user}")

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
    remote_run(client, f"mkdir -p {dest} && chmod 755 {dest}")

    sftp = client.open_sftp()
    uploaded = 0
    for path in iter_local_files():
        rel = path.relative_to(ROOT).as_posix()
        remote_path = posixpath.join(dest, rel)
        sftp_mkdirs(sftp, posixpath.dirname(remote_path))
        sftp.put(str(path), remote_path)
        mode = 0o600 if path.name == ".env" else (path.stat().st_mode & 0o777)
        sftp.chmod(remote_path, mode or 0o644)
        uploaded += 1
        print("put", rel)
    sftp.close()
    print(f"uploaded {uploaded} files")

    remote_run(client, f"sed -i 's/\\r$//' {dest}/deploy/setup_remote.sh && chmod +x {dest}/deploy/setup_remote.sh")
    code = remote_run(client, f"bash {dest}/deploy/setup_remote.sh", timeout=300)
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
