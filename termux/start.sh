#!/data/data/com.termux/files/usr/bin/bash
# Botni fonda ishga tushiradi; yiqilsa yoki internet uzilsa, o'zi qayta yonadi.
DIR="$HOME/QuizBot"
LOG="$DIR/bot.log"

if [ "$1" != "--worker" ]; then
  if pgrep -f "QuizBot/termux/start.sh --worker" >/dev/null; then
    echo "Bot allaqachon ishlayapti. Jurnal: tail -f $LOG"
    exit 0
  fi
  nohup bash "$DIR/termux/start.sh" --worker >/dev/null 2>&1 &
  echo "✅ Bot fonda ishga tushdi. Jurnal: tail -f $LOG   To'xtatish: bash $DIR/termux/stop.sh"
  exit 0
fi

termux-wake-lock 2>/dev/null || true   # telefon uxlaganda ham ishlashi uchun
while true; do
  echo "--- $(date '+%F %T') bot ishga tushmoqda" >> "$LOG"
  proot-distro login ubuntu --termux-home -- bash -c 'cd ~/QuizBot && exec .venv/bin/python -m bot' >> "$LOG" 2>&1
  echo "--- $(date '+%F %T') bot to'xtadi, 10 soniyadan keyin qayta yonadi" >> "$LOG"
  sleep 10
  # jurnal juda kattalashib ketmasin
  [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 5000000 ] && tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
done
