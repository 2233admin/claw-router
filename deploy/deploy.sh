#!/bin/bash
# Deploy claw-router to 新腾讯云 (43.156.202.94 / 10.10.0.6)
set -e

TARGET="root@43.156.202.94"
REMOTE_DIR="/opt/claw-router"

echo "==> Syncing to $TARGET:$REMOTE_DIR"
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.env' --exclude '*.egg-info' \
    -e ssh "$(dirname "$(dirname "$0")")/" "$TARGET:$REMOTE_DIR/"

echo "==> Installing dependencies"
ssh "$TARGET" "cd $REMOTE_DIR && pip install -e . 2>&1 | tail -3"

echo "==> Copying .env if not exists"
scp -n "$(dirname "$(dirname "$0")")/.env" "$TARGET:$REMOTE_DIR/.env" 2>/dev/null || true

echo "==> Installing systemd service"
ssh "$TARGET" "cp $REMOTE_DIR/deploy/claw-router.service /etc/systemd/system/ && systemctl daemon-reload"

echo "==> Restarting service"
ssh "$TARGET" "systemctl restart claw-router && sleep 2 && systemctl status claw-router --no-pager"

echo "==> Done! Test: curl http://10.10.0.6:3456/health"
