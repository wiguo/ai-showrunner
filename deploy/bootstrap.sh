#!/usr/bin/env bash
# One-shot deploy of AI Showrunner on a fresh Ubuntu 22.04 Alibaba Cloud
# Simple Application Server. Run as root:
#   curl -fsSL https://raw.githubusercontent.com/wiguo/ai-showrunner/master/deploy/bootstrap.sh | bash
# It will prompt for your DASHSCOPE_API_KEY (input hidden).
set -euo pipefail

REPO=https://github.com/wiguo/ai-showrunner.git
DIR=/opt/ai-showrunner

echo "== 1/5 packages =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io git curl >/dev/null
systemctl enable --now docker

echo "== 2/5 swap (2G, ffmpeg headroom on small instances) =="
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
free -h | sed -n '1,3p'

echo "== 3/5 code =="
if [ -d "$DIR/.git" ]; then
    git -C "$DIR" pull --ff-only
else
    git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"

echo "== 4/5 API key =="
if [ ! -f .env ]; then
    if [ -n "${DASHSCOPE_API_KEY:-}" ]; then
        printf 'DASHSCOPE_API_KEY=%s\n' "$DASHSCOPE_API_KEY" > .env
    else
        read -rsp "Paste your DASHSCOPE_API_KEY (input hidden): " KEY; echo
        printf 'DASHSCOPE_API_KEY=%s\n' "$KEY" > .env
    fi
    chmod 600 .env
fi

echo "== 5/5 build + run =="
docker build -t showrunner .
docker rm -f showrunner 2>/dev/null || true
docker run -d --name showrunner --restart unless-stopped \
    -p 8080:8080 --env-file .env -v "$DIR/jobs:/app/jobs" showrunner

sleep 3
docker ps --filter name=showrunner --format '{{.Status}}'
IP=$(curl -fsS ifconfig.me || echo "<public-ip>")
echo
echo "Done. Open http://$IP:8080 (make sure TCP 8080 is open in the SAS firewall)."
