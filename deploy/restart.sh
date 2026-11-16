#!/usr/bin/env bash
# Botni qayta ishga tushiradi (systemd bor yoki yo'qligidan qat'i nazar).
DIR="/opt/quizbot"
if [ -d /run/systemd/system ] && systemctl list-unit-files quizbot.service >/dev/null 2>&1; then
  systemctl restart quizbot
else
  pkill -f "quizbot/deploy/run.sh" 2>/dev/null
  pkill -f "python -m bot" 2>/dev/null
  sleep 2
  su -s /bin/bash quizbot -c "nohup $DIR/deploy/run.sh >/dev/null 2>&1 &"
fi
echo "✅ Bot qayta ishga tushirildi."
