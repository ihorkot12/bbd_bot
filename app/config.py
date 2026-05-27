"""
config.py — завантаження налаштувань із .env файлу.

Реальні значення для Black Bear Dojo (заповнити у .env):
  SPREADSHEET_ID=101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg
  REGISTRATION_FORM_ID=1rdsZwpIY93fdXtd5e8-hnfn9Si7bt0fNtmKlfLlZCO8
  OWNER_TELEGRAM_ID=329214126
  TELEGRAM_BOT_TOKEN=<ваш токен від @BotFather>
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)


def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        print(
            f"\n[ПОМИЛКА] Обов'язкова змінна '{key}' не задана.\n"
            f"  Скопіюйте .env.example → .env та заповніть значення.\n",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return value


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _get_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)).strip())
    except ValueError:
        return default


def _get_list(key: str, default: str = "") -> List[str]:
    raw = os.getenv(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]

def _get_int_list(key: str, default: str = "") -> List[int]:
    values: List[int] = []
    for item in _get_list(key, default):
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values


@dataclass
class Config:
    # ── Telegram ──────────────────────────────────────────────────────────────
    # ВАЖЛИВО: ніколи не вкладайте токен у код або git
    telegram_token: str = field(
        default_factory=lambda: _require("TELEGRAM_BOT_TOKEN")
    )
    owner_chat_id: int = field(
        default_factory=lambda: _get_int("OWNER_TELEGRAM_ID", 329214126)
    )

    # ── Google Sheets ─────────────────────────────────────────────────────────
    google_credentials_file: str = field(
        default_factory=lambda: _get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    )
    # Реальний ID таблиці Black Bear Dojo
    spreadsheet_id: str = field(
        default_factory=lambda: _get(
            "SPREADSHEET_ID",
            "101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg"
        )
    )

    # ── Google Form ───────────────────────────────────────────────────────────
    registration_form_id: str = field(
        default_factory=lambda: _get(
            "REGISTRATION_FORM_ID",
            "1rdsZwpIY93fdXtd5e8-hnfn9Si7bt0fNtmKlfLlZCO8"
        )
    )
    registration_form_url: str = field(
        default_factory=lambda: _get(
            "REGISTRATION_FORM_URL",
            "https://docs.google.com/forms/d/e/"
            "1FAIpQLSesT2y1vreDee-V90xP66GaTEPFibCXuGI9czsOK6iqg0HpYA/viewform"
        )
    )
    trial_form_id: str = field(
        default_factory=lambda: _get(
            "TRIAL_FORM_ID",
            "1cgQPkWnNQwvnvtTc4GNUCXBjfedOBvnLe5jGXFD5ZiI"
        )
    )
    trial_form_url: str = field(
        default_factory=lambda: _get(
            "TRIAL_FORM_URL",
            "https://docs.google.com/forms/d/e/"
            "1FAIpQLSc7hWokYpbwC8JnY-VlHgwEcJGsOPBz-xf0aQeepQDWMwHkMA/viewform"
        )
    )
    # Інтервал опитування нових відповідей форми (хвилини)
    form_poll_interval_minutes: int = field(
        default_factory=lambda: _get_int("FORM_POLL_INTERVAL_MINUTES", 60)
    )
    seed_templates_on_startup: bool = field(
        default_factory=lambda: os.getenv("SEED_TEMPLATES_ON_STARTUP", "false").lower() == "true"
    )

    # ── Нагадування про оплату ────────────────────────────────────────────────
    payment_reminder_days: List[int] = field(
        default_factory=lambda: [
            int(d) for d in _get_list("PAYMENT_REMINDER_DAYS", "1,5,10")
        ]
    )

    # ── Розклад ───────────────────────────────────────────────────────────────
    attendance_reminder_time: str = field(
        default_factory=lambda: _get("ATTENDANCE_REMINDER_TIME", "09:00")
    )
    attendance_deadline_time: str = field(
        default_factory=lambda: _get("ATTENDANCE_DEADLINE_TIME", "22:00")
    )
    coach_morning_card_time: str = field(
        default_factory=lambda: _get("COACH_MORNING_CARD_TIME", "07:30")
    )
    attendance_pre_reminder_minutes: List[int] = field(
        default_factory=lambda: _get_int_list("ATTENDANCE_PRE_REMINDER_MINUTES", "60,30")
    )
    parent_absence_followup_time: str = field(
        default_factory=lambda: _get("PARENT_ABSENCE_FOLLOWUP_TIME", "13:00")
    )
    digest_time: str = field(
        default_factory=lambda: _get("DIGEST_TIME", "08:00")
    )

    # ── Клуб ─────────────────────────────────────────────────────────────────
    club_name: str = field(
        default_factory=lambda: _get("CLUB_NAME", "Black Bear Dojo")
    )
    club_address: str = field(
        default_factory=lambda: _get("CLUB_ADDRESS", "Київ, вул. Прикладна, 1")
    )
    club_phone: str = field(
        default_factory=lambda: _get("CLUB_PHONE", "+380XXXXXXXXX")
    )
    club_maps_link: str = field(
        default_factory=lambda: _get("CLUB_MAPS_LINK", "")
    )
    club_website: str = field(
        default_factory=lambda: _get("CLUB_WEBSITE", "")
    )
    parents_channel_id: str = field(
        default_factory=lambda: _get("PARENTS_CHANNEL_ID", "")
    )
    birthday_check_time: str = field(
        default_factory=lambda: _get("BIRTHDAY_CHECK_TIME", "09:00")
    )
    club_price_text: str = field(
        default_factory=lambda: _get(
            "CLUB_PRICE_TEXT",
            "Місячний абонемент: уточнюйте у адміністратора"
        )
    )
    club_schedule_text: str = field(
        default_factory=lambda: _get(
            "CLUB_SCHEDULE_TEXT",
            "Пн/Ср/Пт — уточнюйте у адміністратора"
        )
    )

    # ── Misc ──────────────────────────────────────────────────────────────────
    timezone: str = field(
        default_factory=lambda: _get("TIMEZONE", "Europe/Kyiv")
    )
    log_level: str = field(
        default_factory=lambda: _get("LOG_LEVEL", "INFO")
    )
    log_file: str = field(
        default_factory=lambda: _get("LOG_FILE", "")
    )

    # Якщо True — Google Sheets не ініціалізується (для тестів без credentials)
    dry_run: bool = field(
        default_factory=lambda: os.getenv("DRY_RUN", "false").lower() == "true"
    )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    global _config
    _config = None
