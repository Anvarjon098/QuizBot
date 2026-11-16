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

echo "==> 5/5 Xizmat yaratilmoqda..."
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
echo "   Yangilash:     bash $DIR/deploy/update_vps.sh"
