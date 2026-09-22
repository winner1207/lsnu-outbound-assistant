#!/bin/bash
set -euo pipefail
DEST=/opt/lsnu-outbound-assistant
cd "$DEST"

if [ ! -d .git ]; then
  echo "not a git checkout: $DEST" >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "missing $DEST/.env" >&2
  exit 1
fi

export GIT_TERMINAL_PROMPT=0
git fetch origin
git pull --ff-only origin main

if [ -x .venv/bin/pip ]; then
  .venv/bin/pip install -r requirements.txt
else
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
fi

cp "$DEST/deploy/lsnu-assistant.service" /etc/systemd/system/lsnu-assistant.service
cp "$DEST/deploy/nginx.conf" /etc/nginx/sites-available/lsnu-outbound-assistant
ln -sfn /etc/nginx/sites-available/lsnu-outbound-assistant /etc/nginx/sites-enabled/lsnu-outbound-assistant
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
