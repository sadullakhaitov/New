"""Sozlamalar: muhit o'zgaruvchilari yoki .env fayldan o'qiladi."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

# O'zbekistonda yozgi vaqt yo'q, shuning uchun doimiy UTC+5.
TASHKENT_TZ = timezone(timedelta(hours=5), name="Asia/Tashkent")

PROJECT_DIR = Path(__file__).resolve().parent.parent
WEBAPP_DIR = PROJECT_DIR / "webapp"


def load_dotenv(path: Path) -> None:
    """Oddiy .env o'quvchi: KEY=VALUE qatorlari, mavjud o'zgaruvchilar ustidan yozilmaydi."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True)
class Config:
    bot_token: str
    base_url: str
    mode: str
    host: str
    port: int
    data_dir: Path
    superadmins: frozenset[int]
    database_url: str = ""
    keepalive: bool = False

    @property
    def database(self) -> str:
        """PostgreSQL manzili (DATABASE_URL) yoki SQLite fayl yo'li."""
        return self.database_url or str(self.data_dir / "emirfood.db")

    @property
    def webapp_url(self) -> str | None:
        """Telegram Mini App faqat HTTPS manzilda ochiladi."""
        if self.base_url.startswith("https://"):
            return self.base_url + "/"
        return None

    @property
    def webhook_path(self) -> str:
        return "/tg/webhook"

    @property
    def webhook_secret(self) -> str:
        # Token asosida barqaror maxfiy kalit (Telegram faqat A-Z, a-z, 0-9, _ va - ga ruxsat beradi).
        return hashlib.sha256(("wh:" + self.bot_token).encode()).hexdigest()[:48]


def _parse_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return frozenset(ids)


def load_config() -> Config:
    load_dotenv(PROJECT_DIR / ".env")
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN topilmadi. .env.example dan nusxa olib .env yarating.")
    mode = os.environ.get("MODE", "polling").strip().lower()
    if mode not in {"polling", "webhook"}:
        raise SystemExit("MODE faqat 'polling' yoki 'webhook' bo'lishi mumkin.")
    # Render o'z manzilini RENDER_EXTERNAL_URL orqali beradi — BASE_URL yozilmasa shu olinadi.
    base_url = (os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if mode == "webhook" and not base_url.startswith("https://"):
        raise SystemExit("webhook rejimi uchun BASE_URL https:// bilan boshlanishi kerak.")
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_DIR / data_dir
    return Config(
        bot_token=token,
        base_url=base_url,
        mode=mode,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        data_dir=data_dir,
        superadmins=_parse_ids(os.environ.get("SUPERADMIN_IDS", "")),
        database_url=os.environ.get("DATABASE_URL", "").strip(),
        keepalive=keepalive_enabled(os.environ, base_url),
    )


def keepalive_enabled(env, base_url: str) -> bool:
    """O'zini uyg'otib turish: Render'da (RENDER=true) avtomatik yoqiladi, KEEPALIVE=0 bilan o'chiriladi."""
    flag = (env.get("KEEPALIVE") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if not base_url.startswith("https://"):
        return False
    return flag in {"1", "true", "yes", "on"} or (env.get("RENDER") or "").lower() == "true"
