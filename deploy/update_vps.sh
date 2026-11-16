#!/usr/bin/env bash
# GitHub'dagi yangi kodni yuklab, botni qayta ishga tushiradi.
set -e
DIR="/opt/quizbot"
sudo -u quizbot git -C "$DIR" pull --ff-only
sudo -u quizbot "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
systemctl restart quizbot
echo "✅ Yangilandi."
