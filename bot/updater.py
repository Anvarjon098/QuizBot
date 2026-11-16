"""Botni GitHub'dagi eng so'nggi kod bilan yangilash (/update buyrug'i uchun).

Kod arxiv ko'rinishida yuklanadi va joriy papkaga yoziladi; .env, baza, jurnal va .venv tegilmaydi.
Yangilangach, bot to'xtaydi va uni ishga tushirgan skript (run.sh / systemd) qayta yoqadi.
"""

import asyncio
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import aiohttp

APP_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = APP_DIR / ".version"
NOTICE_FILE = APP_DIR / ".update_notice"

REPO = os.getenv("UPDATE_REPO", "Anvarjon098/QuizBot")
BRANCH = os.getenv("UPDATE_BRANCH", "claude/claude-qhb9qq")

# Yangilanishda hech qachon ustidan yozilmaydigan fayllar
PROTECTED = {".env", ".venv", ".git", ".version", ".update_notice", ".python", "bot.log"}


@dataclass
class Commit:
    sha: str
    message: str


class UpdateError(Exception):
    pass


def current_version() -> str | None:
    try:
        return VERSION_FILE.read_text().strip() or None
    except OSError:
        return None


async def latest_commit() -> Commit:
    url = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.get(url, headers={"Accept": "application/vnd.github+json"}) as r:
                if r.status != 200:
                    raise UpdateError(f"GitHub javobi: {r.status}")
                data = await r.json()
    except aiohttp.ClientError as e:
        raise UpdateError(f"GitHub'ga ulanib bo'lmadi: {e}") from e
    return Commit(data["sha"], data["commit"]["message"].splitlines()[0])


async def _download(sha: str) -> bytes:
    url = f"https://codeload.github.com/{REPO}/tar.gz/{sha}"
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=120)) as s:
            async with s.get(url) as r:
                if r.status != 200:
                    raise UpdateError(f"Arxivni yuklab bo'lmadi: {r.status}")
                return await r.read()
    except aiohttp.ClientError as e:
        raise UpdateError(f"Arxivni yuklab bo'lmadi: {e}") from e


def install_archive(data: bytes, app_dir: Path = APP_DIR) -> bool:
    """Arxivni app_dir'ga yozadi. requirements.txt o'zgargan bo'lsa True qaytaradi."""
    req = app_dir / "requirements.txt"
    old_req = req.read_bytes() if req.exists() else b""
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:  # eski Python
                for m in tar.getmembers():
                    if m.name.startswith("/") or ".." in Path(m.name).parts or m.issym() or m.islnk():
                        raise UpdateError("Arxivda xavfli fayl bor")
                tar.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "bot" / "__main__.py").exists():
            raise UpdateError("Arxiv tuzilishi kutilganidek emas")
        src = roots[0]
        for item in src.iterdir():
            if item.name in PROTECTED or item.suffix in {".db"}:
                continue
            dest = app_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
    return req.read_bytes() != old_req


async def _pip_install(app_dir: Path = APP_DIR) -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "-r", str(app_dir / "requirements.txt"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise UpdateError("Kutubxonalarni o'rnatib bo'lmadi:\n" + out.decode(errors="replace")[-500:])


async def apply_update(commit: Commit) -> None:
    data = await _download(commit.sha)
    req_changed = await asyncio.to_thread(install_archive, data)
    if req_changed:
        await _pip_install()
    VERSION_FILE.write_text(commit.sha)


def save_notice(chat_id: int, commit: Commit) -> None:
    NOTICE_FILE.write_text(json.dumps({"chat_id": chat_id, "sha": commit.sha, "message": commit.message}))


def pop_notice() -> dict | None:
    try:
        data = json.loads(NOTICE_FILE.read_text())
    except (OSError, ValueError):
        return None
    NOTICE_FILE.unlink(missing_ok=True)
    return data
