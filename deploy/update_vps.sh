#!/usr/bin/env bash
# GitHub'dagi yangi kodni yuklab, botni qayta ishga tushiradi.
set -e
DIR="/opt/quizbot"
git config --global --add safe.directory "$DIR"
git -C "$DIR" pull --ff-only
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
chown -R quizbot:quizbot "$DIR"
bash "$DIR/deploy/restart.sh"
