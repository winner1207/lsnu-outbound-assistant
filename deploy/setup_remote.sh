#!/bin/bash
set -euo pipefail
DEST=/opt/lsnu-outbound-assistant
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv python3-pip nginx libgl1 libglib2.0-0 git
cd "$DEST"
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
cp "$DEST/deploy/lsnu-assistant.service" /etc/systemd/system/lsnu-assistant.service
cp "$DEST/deploy/nginx.conf" /etc/nginx/sites-available/lsnu-outbound-assistant
ln -sfn /etc/nginx/sites-available/lsnu-outbound-assistant /etc/nginx/sites-enabled/lsnu-outbound-assistant
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now lsnu-assistant
systemctl restart lsnu-assistant
systemctl reload nginx
sleep 3
curl -fsS http://127.0.0.1:8000/api/health
echo
curl -fsS http://127.0.0.1/api/health
echo
systemctl --no-pager --full status lsnu-assistant | head -n 20
