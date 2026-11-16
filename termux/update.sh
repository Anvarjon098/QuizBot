#!/data/data/com.termux/files/usr/bin/bash
# GitHub'dagi yangi kodni yuklab, botni qayta ishga tushiradi.
DIR="$HOME/QuizBot"
bash "$DIR/termux/stop.sh"
git -C "$DIR" pull --ff-only
proot-distro login ubuntu --termux-home -- bash -c 'cd ~/QuizBot && .venv/bin/pip install -q -r requirements.txt'
bash "$DIR/termux/start.sh"
