"""
scripts/bootstrap_sheets.py — ініціалізація Google Sheets для Black Bear Dojo Bot V2.

Використання:
    python scripts/bootstrap_sheets.py
    python scripts/bootstrap_sheets.py --spreadsheet-id <ID>   # перевизначити ID
    python scripts/bootstrap_sheets.py --dry-run               # тільки перевірити

Що робить:
  1. Підключається до Google Sheets (потрібен credentials.json)
  2. Для кожного необхідного аркуша:
     - Якщо аркуш відсутній → створює з правильними заголовками
     - Якщо аркуш є → перевіряє заголовки (додає відсутні колонки)
  3. Додає початкові записи у settings та message_templates (якщо порожні)
  4. Додає власника у users_roles (якщо OWNER_TELEGRAM_ID задано)
"""
from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

# Додаємо корінь проекту до sys.path
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(dotenv_path=_root / ".env", override=False)

from app.repositories.google_sheets import SHEET_HEADERS

# ── Дефолтні налаштування (записуються у settings) ───────────────────────────

DEFAULT_SETTINGS = [
    ("owner_telegram_id",    os.getenv("OWNER_TELEGRAM_ID", "329214126"),
     "Telegram ID власника клубу"),
    ("spreadsheet_id",       os.getenv("SPREADSHEET_ID",
                                       "101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg"),
     "ID таблиці Google Sheets"),
    ("registration_form_id", os.getenv("REGISTRATION_FORM_ID",
                                       "1rdsZwpIY93fdXtd5e8-hnfn9Si7bt0fNtmKlfLlZCO8"),
     "ID Google Form реєстрації"),
    ("registration_form_url", os.getenv("REGISTRATION_FORM_URL",
                                        "https://docs.google.com/forms/d/e/"
                                        "1FAIpQLSesT2y1vreDee-V90xP66GaTEPFibCXuGI9czsOK6iqg0HpYA/viewform"),
     "Посилання на форму реєстрації"),
    ("payment_reminder_days", os.getenv("PAYMENT_REMINDER_DAYS", "1,5,10"),
     "Дні місяця для нагадувань про оплату"),
    ("daily_digest_time",     os.getenv("DIGEST_TIME", "08:00"),
     "Час щоденного дайджесту"),
    ("attendance_reminder_time", os.getenv("ATTENDANCE_REMINDER_TIME", "09:00"),
     "Час нагадування тренерам"),
    ("attendance_deadline_time", os.getenv("ATTENDANCE_DEADLINE_TIME", "22:00"),
     "Час дедлайну закриття журналу"),
    ("timezone",              os.getenv("TIMEZONE", "Europe/Kyiv"),
     "Часовий пояс"),
    ("club_name",             os.getenv("CLUB_NAME", "Black Bear Dojo"),
     "Назва клубу"),
    ("club_address",          os.getenv("CLUB_ADDRESS", "Київ, вул. Прикладна, 1"),
     "Адреса клубу"),
    ("club_phone",            os.getenv("CLUB_PHONE", "+380XXXXXXXXX"),
     "Телефон клубу"),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Google Sheets для Black Bear Dojo Bot V2"
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("SPREADSHEET_ID", "101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg"),
        help="ID Google Spreadsheet (або SPREADSHEET_ID у .env)",
    )
    parser.add_argument(
        "--credentials",
        default=os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        help="Шлях до credentials.json (Service Account)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Тільки перевірити, нічого не записувати",
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Black Bear Dojo Bot V2 — Bootstrap Sheets")
    print(f"  Spreadsheet ID: {args.spreadsheet_id}")
    print(f"  Credentials:    {args.credentials}")
    print(f"  Dry run:        {args.dry_run}")
    print(f"{'='*60}\n")

    # ── Підключення ──────────────────────────────────────────────────────────
    try:
        from app.repositories.google_sheets import build_google_sheets_client
        client = build_google_sheets_client(args.credentials)
        ss = client.open_by_key(args.spreadsheet_id)
        print(f"✅ Підключено до таблиці: '{ss.title}'")
    except Exception as e:
        print(f"❌ Помилка підключення: {e}")
        print(
            "\nПерегляньте:\n"
            "  1. credentials.json — правильний шлях та вміст\n"
            "  2. Service Account має доступ до таблиці (Editor)\n"
            "  3. SPREADSHEET_ID у .env відповідає реальній таблиці\n"
        )
        sys.exit(1)

    # ── Отримуємо існуючі аркуші ─────────────────────────────────────────────
    existing_sheets = {ws.title: ws for ws in ss.worksheets()}
    print(f"Існуючі аркуші ({len(existing_sheets)}): {', '.join(existing_sheets.keys())}\n")

    # ── Bootstrap кожного аркуша ─────────────────────────────────────────────
    for sheet_name, headers in SHEET_HEADERS.items():
        _bootstrap_sheet(ss, existing_sheets, sheet_name, headers, args.dry_run)

    # ── Дефолтні settings ────────────────────────────────────────────────────
    if not args.dry_run:
        _seed_settings(ss, DEFAULT_SETTINGS)

    # ── Дефолтні message_templates ───────────────────────────────────────────
    if not args.dry_run:
        _seed_templates(ss)

    # ── Власник у users_roles ────────────────────────────────────────────────
    owner_id = os.getenv("OWNER_TELEGRAM_ID", "329214126")
    if owner_id and not args.dry_run:
        _seed_owner(ss, owner_id)

    print(f"\n{'='*60}")
    print("  ✅ Bootstrap завершено!")
    if args.dry_run:
        print("  (DRY RUN — нічого не записано)")
    print(f"  Таблиця: https://docs.google.com/spreadsheets/d/{args.spreadsheet_id}/edit")
    print(f"{'='*60}\n")


def _bootstrap_sheet(ss, existing: dict, name: str, headers: list, dry_run: bool) -> None:
    """Створює аркуш або перевіряє/додає заголовки."""
    if name not in existing:
        if dry_run:
            print(f"  [DRY] Буде створено аркуш: '{name}' ({len(headers)} колонок)")
            return
        try:
            ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers) + 5)
            ws.append_row(headers, value_input_option="USER_ENTERED")
            print(f"  ✅ Створено аркуш: '{name}'")
        except Exception as e:
            print(f"  ⚠️  Помилка створення '{name}': {e}")
    else:
        ws = existing[name]
        try:
            current_headers = ws.row_values(1)
        except Exception:
            current_headers = []

        missing = [h for h in headers if h not in current_headers]
        if missing:
            if dry_run:
                print(f"  [DRY] У '{name}' відсутні колонки: {missing}")
                return
            try:
                # Додаємо відсутні колонки праворуч
                next_col = len(current_headers) + 1
                for i, col_name in enumerate(missing):
                    ws.update_cell(1, next_col + i, col_name)
                print(f"  🔧 Додано колонки до '{name}': {missing}")
            except Exception as e:
                print(f"  ⚠️  Помилка додавання колонок до '{name}': {e}")
        else:
            print(f"  ✓  Аркуш '{name}' — OK ({len(current_headers)} колонок)")


def _seed_settings(ss, settings: list) -> None:
    """Додає початкові налаштування у settings (тільки якщо порожні)."""
    try:
        ws = ss.worksheet("settings")
        records = ws.get_all_records(empty2zero=False, default_blank="")
        existing_keys = {str(r.get("key", "")).strip() for r in records}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        added = 0
        for key, value, desc in settings:
            if key not in existing_keys:
                ws.append_row([key, value, desc, now])
                added += 1

        if added:
            print(f"  ✅ Додано {added} налаштувань у 'settings'")
        else:
            print("  ✓  'settings' — вже заповнено")
    except Exception as e:
        print(f"  ⚠️  Помилка seed settings: {e}")


def _seed_templates(ss) -> None:
    """Засіває дефолтні шаблони повідомлень."""
    try:
        from app.services.templates import DEFAULT_TEMPLATES
        import uuid
        ws = ss.worksheet("message_templates")
        records = ws.get_all_records(empty2zero=False, default_blank="")
        existing_names = {str(r.get("name", "")).strip() for r in records}

        added = 0
        for name, text in DEFAULT_TEMPLATES.items():
            if name not in existing_names:
                ws.append_row([str(uuid.uuid4())[:8], name, text, ""])
                added += 1

        if added:
            print(f"  ✅ Додано {added} шаблонів у 'message_templates'")
        else:
            print("  ✓  'message_templates' — вже заповнено")
    except Exception as e:
        print(f"  ⚠️  Помилка seed templates: {e}")


def _seed_owner(ss, owner_id: str) -> None:
    """Додає власника у users_roles (якщо ще нема)."""
    try:
        ws = ss.worksheet("users_roles")
        records = ws.get_all_records(empty2zero=False, default_blank="")
        existing_ids = {str(r.get("telegram_id", "")).strip() for r in records}

        if owner_id not in existing_ids:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ws.append_row([owner_id, "", "Власник клубу", "owner", "true", "", now])
            print(f"  ✅ Власника ({owner_id}) додано до 'users_roles'")
        else:
            print(f"  ✓  Власник ({owner_id}) вже є у 'users_roles'")
    except Exception as e:
        print(f"  ⚠️  Помилка seed owner: {e}")


if __name__ == "__main__":
    main()
