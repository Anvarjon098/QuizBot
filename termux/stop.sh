#!/data/data/com.termux/files/usr/bin/bash
# Botni to'xtatadi.
pkill -f "QuizBot/termux/start.sh --worker"
pkill -f "python -m bot"
termux-wake-unlock 2>/dev/null || true
echo "⏹ Bot to'xtatildi."
