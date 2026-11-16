#!/usr/bin/env bash
# QuizBot'ni Ubuntu/Debian VPS'ga o'rnatish va systemd xizmati sifatida ishga tushirish.
# Ishga tushirish (root sifatida):  bash install_vps.sh
set -e
REPO="https://github.com/Anvarjon098/QuizBot.git"
BRANCH="claude/claude-qhb9qq"
DIR="/opt/quizbot"
SERVICE="quizbot"

if [ "$(id -u)" -ne 0 ]; then
  echo "Skriptni root sifatida ishga tushiring:  sudo bash install_vps.sh"; exit 1
fi

echo "==> 1/5 Kerakli paketlar o'rnatilmoqda..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git python3 python3-venv

echo "==> 2/5 Bot kodi yuklanmoqda..."
id quizbot >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin quizbot
git config --global --add safe.directory "$DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone -b "$BRANCH" "$REPO" "$DIR"
fi

echo "==> 3/5 Python kutubxonalari o'rnatilmoqda..."
[ -d "$DIR/.venv" ] || python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -U pip
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"

echo "==> 4/5 Sozlamalar..."
if [ ! -f "$DIR/.env" ]; then
  read -r -p "BotFather bergan bot tokenini kiriting: " TOKEN
  printf 'BOT_TOKEN=%s\nADMIN_IDS=1085222742\nDB_PATH=quizbot.db\n' "$TOKEN" > "$DIR/.env"
fi
chown -R quizbot:quizbot "$DIR"
chmod 600 "$DIR/.env"

echo "==> 5/5 Bot ishga tushirilmoqda..."
cat > "$DIR/deploy/run.sh" <<'RUN'
#!/usr/bin/env bash
# systemd bo'lmagan serverlar uchun: bot yiqilsa, 5 soniyadan keyin qayta yonadi.
DIR="/opt/quizbot"
cd "$DIR"
while true; do
  echo "--- $(date '+%F %T') bot ishga tushmoqda" >> "$DIR/bot.log"
  "$DIR/.venv/bin/python" -m bot >> "$DIR/bot.log" 2>&1
  sleep 5
  [ "$(stat -c %s "$DIR/bot.log")" -gt 5000000 ] && tail -n 2000 "$DIR/bot.log" > "$DIR/bot.log.tmp" && mv "$DIR/bot.log.tmp" "$DIR/bot.log"
done
RUN
chmod +x "$DIR/deploy/run.sh"; chown quizbot:quizbot "$DIR/deploy/run.sh"

if [ -d /run/systemd/system ]; then
  cat > /etc/systemd/system/$SERVICE.service <<UNIT
[Unit]
Description=QuizBot (Telegram)
After=network-online.target
Wants=network-online.target

[Service]
User=quizbot
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python -m bot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now $SERVICE
  sleep 3
  systemctl --no-pager status $SERVICE | head -n 5
  echo
  echo "✅ Bot ishga tushdi va server qayta yonganda ham avtomatik ishlaydi."
  echo "   Jurnal:        journalctl -u $SERVICE -f"
  echo "   Qayta yoqish:  systemctl restart $SERVICE"
else
  # systemd yo'q (konteyner) — fon jarayoni + qayta yonganda avtomatik ishga tushirish
  pkill -f "quizbot/deploy/run.sh" 2>/dev/null || true
  pkill -f "python -m bot" 2>/dev/null || true
  sleep 1
  su -s /bin/bash quizbot -c "nohup $DIR/deploy/run.sh >/dev/null 2>&1 &"
  BOOT_LINE="@reboot su -s /bin/bash quizbot -c 'nohup $DIR/deploy/run.sh >/dev/null 2>&1 &'"
  if command -v crontab >/dev/null || apt-get install -y cron >/dev/null 2>&1; then
    ( crontab -l 2>/dev/null | grep -v "quizbot/deploy/run.sh"; echo "$BOOT_LINE" ) | crontab -
    service cron start >/dev/null 2>&1 || cron 2>/dev/null || true
  fi
  # zaxira: root SSH orqali kirganda bot ishlamayotgan bo'lsa, o'zi yonadi
  grep -q "quizbot/deploy/run.sh" /root/.bashrc 2>/dev/null || \
    echo "pgrep -f quizbot/deploy/run.sh >/dev/null || su -s /bin/bash quizbot -c 'nohup $DIR/deploy/run.sh >/dev/null 2>&1 &'" >> /root/.bashrc
  sleep 8
  tail -n 3 "$DIR/bot.log" 2>/dev/null || true
  echo
  echo "✅ Bot fonda ishga tushdi."
  echo "   Jurnal:        tail -f $DIR/bot.log"
  echo "   Qayta yoqish:  bash $DIR/deploy/restart.sh"
fi
echo "   Yangilash:     bash $DIR/deploy/update_vps.sh"
