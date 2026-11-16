#!/data/data/com.termux/files/usr/bin/bash
# QuizBot'ni Android telefonga (Termux) o'rnatish.
# Ishga tushirish:  bash install.sh
set -e
REPO="https://github.com/Anvarjon098/QuizBot.git"
BRANCH="claude/claude-qhb9qq"
DIR="$HOME/QuizBot"

echo "==> 1/5 Termux paketlari o'rnatilmoqda..."
pkg update -y
pkg install -y git proot-distro util-linux

echo "==> 2/5 Bot kodi yuklanmoqda..."
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone -b "$BRANCH" "$REPO" "$DIR"
fi

echo "==> 3/5 Ubuntu muhiti o'rnatilmoqda (bir marta, biroz vaqt oladi)..."
if [ ! -d "$PREFIX/var/lib/proot-distro/installed-rootfs/ubuntu" ]; then
  proot-distro install ubuntu
fi

echo "==> 4/5 Python va kutubxonalar o'rnatilmoqda..."
proot-distro login ubuntu --termux-home -- bash -c '
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 python3-venv
  cd ~/QuizBot
  [ -d .venv ] || python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
'

echo "==> 5/5 Sozlamalar..."
if [ ! -f "$DIR/.env" ]; then
  read -r -p "BotFather bergan bot tokenini kiriting: " TOKEN
  printf 'BOT_TOKEN=%s\nADMIN_IDS=1085222742\nDB_PATH=quizbot.db\n' "$TOKEN" > "$DIR/.env"
  chmod 600 "$DIR/.env"
fi

# Eski testlar bazasi Download papkasida bo'lsa, ko'chirib olinadi
if [ ! -f "$DIR/quizbot.db" ]; then
  [ -d "$HOME/storage" ] || termux-setup-storage || true
  sleep 3
  if [ -f "$HOME/storage/downloads/quizbot.db" ]; then
    cp "$HOME/storage/downloads/quizbot.db" "$DIR/quizbot.db"
    echo "    Testlar bazasi ko'chirildi ✅"
  else
    echo "    Download papkasida quizbot.db topilmadi — yangi bo'sh baza yaratiladi."
  fi
fi

# Telefon qayta yonganda avtomatik ishga tushirish (Termux:Boot ilovasi kerak)
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/quizbot" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
nohup bash "$HOME/QuizBot/termux/start.sh" >/dev/null 2>&1 &
BOOT
chmod +x "$HOME/.termux/boot/quizbot" "$DIR"/termux/*.sh

echo
echo "✅ O'rnatildi! Botni ishga tushirish:  bash ~/QuizBot/termux/start.sh"
