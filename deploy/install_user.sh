#!/usr/bin/env bash
# QuizBot'ni root huquqisiz (oddiy foydalanuvchi sifatida) o'rnatish va ishga tushirish.
# Ishga tushirish:  bash install_user.sh
set -e
BRANCH="claude/claude-qhb9qq"
TARBALL="https://codeload.github.com/Anvarjon098/QuizBot/tar.gz/refs/heads/$BRANCH"
DIR="$HOME/QuizBot"

echo "==> 1/4 Bot kodi yuklanmoqda..."
mkdir -p "$DIR"
TMP="$(mktemp -d)"
curl -fsSL "$TARBALL" | tar -xz -C "$TMP" --strip-components=1
# .env, baza, jurnal va .venv saqlanib qoladi — faqat kod yangilanadi
cp -r "$TMP"/. "$DIR"/
rm -rf "$TMP"
cd "$DIR"

echo "==> 2/4 Python kutubxonalari o'rnatilmoqda..."
PY="python3"
if [ -x "$DIR/.venv/bin/python" ] || python3 -m venv "$DIR/.venv" >/dev/null 2>&1; then
  PY="$DIR/.venv/bin/python"
  "$PY" -m pip install -q --no-cache-dir -r requirements.txt
else
  rm -rf "$DIR/.venv"
  python3 -m pip install -q --no-cache-dir --user -r requirements.txt 2>/dev/null \
    || python3 -m pip install -q --no-cache-dir --user --break-system-packages -r requirements.txt
fi
echo "$PY" > "$DIR/.python"

echo "==> 3/4 Sozlamalar..."
if [ ! -f "$DIR/.env" ]; then
  read -r -p "BotFather bergan bot tokenini kiriting: " TOKEN
  printf 'BOT_TOKEN=%s\nADMIN_IDS=1085222742\nDB_PATH=quizbot.db\n' "$TOKEN" > "$DIR/.env"
fi
chmod 600 "$DIR/.env"

cat > "$DIR/run.sh" <<'RUN'
#!/usr/bin/env bash
# Bot yiqilsa, 5 soniyadan keyin qayta yonadi.
DIR="$HOME/QuizBot"
cd "$DIR"
PY="$(cat "$DIR/.python" 2>/dev/null || echo python3)"
while true; do
  echo "--- $(date '+%F %T') bot ishga tushmoqda" >> bot.log
  "$PY" -m bot >> bot.log 2>&1
  sleep 5
  [ "$(stat -c %s bot.log)" -gt 2000000 ] && tail -n 1000 bot.log > bot.log.tmp && mv bot.log.tmp bot.log
done
RUN
cat > "$DIR/start.sh" <<'S'
#!/usr/bin/env bash
# boshqa skript (masalan, server o'zi) ishga tushirgan nusxa bo'lsa ham ikkinchisi yoqilmaydi
if pgrep -f "QuizBot/run.sh" >/dev/null || pgrep -f -- "python[0-9.]* -m bot$" >/dev/null; then
  echo "Bot allaqachon ishlayapti."; exit 0
fi
setsid nohup bash "$HOME/QuizBot/run.sh" >/dev/null 2>&1 < /dev/null &
echo "✅ Bot ishga tushdi. Jurnal: tail -f ~/QuizBot/bot.log"
S
cat > "$DIR/stop.sh" <<'S'
#!/usr/bin/env bash
pkill -f "QuizBot/run.sh"; pkill -f -- "-m bot$"
echo "⏹ Bot to'xtatildi."
S
cat > "$DIR/update.sh" <<'S'
#!/usr/bin/env bash
bash "$HOME/QuizBot/stop.sh"
curl -fsSL https://raw.githubusercontent.com/Anvarjon098/QuizBot/claude/claude-qhb9qq/deploy/install_user.sh | bash
S
chmod +x "$DIR"/*.sh

# Serverga SSH orqali kirganda bot ishlamayotgan bo'lsa, o'zi yonadi
for rc in "$HOME/.bashrc" "$HOME/.profile"; do
  grep -q "QuizBot/start.sh" "$rc" 2>/dev/null || echo 'bash "$HOME/QuizBot/start.sh" >/dev/null 2>&1' >> "$rc"
done
# cron bo'lsa — konteyner qayta yonganda ham
if command -v crontab >/dev/null 2>&1; then
  ( crontab -l 2>/dev/null | grep -v "QuizBot/start.sh"; echo "@reboot bash $DIR/start.sh"; echo "*/5 * * * * bash $DIR/start.sh >/dev/null 2>&1" ) | crontab - 2>/dev/null || true
fi

echo "==> 4/4 Bot ishga tushirilmoqda..."
if pgrep -f -- "python[0-9.]* -m bot$" >/dev/null && ! pgrep -f "QuizBot/run.sh" >/dev/null; then
  # botni boshqa skript yoqqan va o'zi qayta yoqadi — faqat qayta ishga tushiramiz
  pkill -f -- "python[0-9.]* -m bot$" || true
  echo "✅ Bot qayta ishga tushirilmoqda (uni server skripti yoqadi)."
else
  bash "$DIR/stop.sh" >/dev/null 2>&1 || true
  sleep 1
  bash "$DIR/start.sh"
fi
sleep 10
tail -n 3 "$DIR/bot.log"
echo
echo "Buyruqlar:  bash ~/QuizBot/start.sh | stop.sh | update.sh    Jurnal: tail -f ~/QuizBot/bot.log"
