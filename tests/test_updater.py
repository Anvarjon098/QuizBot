import io
import tarfile

import pytest

from bot import updater


def make_tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"Anvarjon098-QuizBot-abc123/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_install_archive_keeps_secrets_and_db(tmp_path):
    (tmp_path / ".env").write_text("BOT_TOKEN=secret")
    (tmp_path / "quizbot.db").write_bytes(b"DB")
    (tmp_path / "requirements.txt").write_text("aiogram==1\n")
    (tmp_path / "bot").mkdir()
    (tmp_path / "bot" / "__main__.py").write_text("old")
    data = make_tar({
        "bot/__main__.py": b"new",
        "bot/extra.py": b"x",
        "requirements.txt": b"aiogram==1\n",
        ".env": b"BOT_TOKEN=hacked",
        "quizbot.db": b"EMPTY",
    })
    assert updater.install_archive(data, tmp_path) is False
    assert (tmp_path / "bot" / "__main__.py").read_text() == "new"
    assert (tmp_path / "bot" / "extra.py").exists()
    assert (tmp_path / ".env").read_text() == "BOT_TOKEN=secret"
    assert (tmp_path / "quizbot.db").read_bytes() == b"DB"


def test_install_archive_detects_requirements_change(tmp_path):
    (tmp_path / "requirements.txt").write_text("a==1\n")
    data = make_tar({"bot/__main__.py": b"m", "requirements.txt": b"a==2\n"})
    assert updater.install_archive(data, tmp_path) is True


def test_install_archive_rejects_foreign_archive(tmp_path):
    with pytest.raises(updater.UpdateError):
        updater.install_archive(make_tar({"readme.txt": b"hi"}), tmp_path)


def test_notice_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "NOTICE_FILE", tmp_path / ".update_notice")
    assert updater.pop_notice() is None
    updater.save_notice(5, updater.Commit("abcdef123", "Fix"))
    assert updater.pop_notice() == {"chat_id": 5, "sha": "abcdef123", "message": "Fix"}
    assert updater.pop_notice() is None
