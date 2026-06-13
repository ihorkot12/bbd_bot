"""Railway bootstrap for Black Bear Dojo Bot.

The original GitHub upload contains the app package inside
black-bear-dojo-bot-v2.zip. Railway starts this file, extracts that package,
applies the small production hotfixes, then runs app.main.
"""
from __future__ import annotations

import base64
import json
import os
import runpy
import shutil
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ZIP_PATH = ROOT / "black-bear-dojo-bot-v2.zip"
APP_ROOT = ROOT / ".runtime_app" / "black-bear-dojo-bot-v2"
LOCAL_APP_OVERRIDE = ROOT / "app"


def _running_on_railway() -> bool:
    return any(
        os.getenv(name)
        for name in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")
    )


def _enable_real_data_mode() -> None:
    if _running_on_railway():
        os.environ["DRY_RUN"] = "false"


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected patch target not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _ensure_runtime_app() -> None:
    if not ZIP_PATH.exists():
        raise RuntimeError(f"Missing deploy archive: {ZIP_PATH.name}")
    if not (APP_ROOT / "app" / "main.py").exists():
        APP_ROOT.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ZIP_PATH) as archive:
            archive.extractall(APP_ROOT.parent)


def _apply_hotfixes() -> None:
    attendance = APP_ROOT / "app" / "services" / "attendance.py"
    scheduler = APP_ROOT / "app" / "scheduler.py"
    bot = APP_ROOT / "app" / "bot.py"

    text = attendance.read_text(encoding="utf-8")
    if "from zoneinfo import ZoneInfo" not in text:
        text = text.replace(
            "from datetime import date, datetime, timedelta\n",
            "from datetime import date, datetime, timedelta\nfrom zoneinfo import ZoneInfo\n",
            1,
        )
    text = text.replace(
        "now = now or datetime.now()\n",
        'now = now or datetime.now(ZoneInfo("Europe/Kyiv"))\n',
        1,
    )
    attendance.write_text(text, encoding="utf-8")

    text = scheduler.read_text(encoding="utf-8")
    if "from zoneinfo import ZoneInfo" not in text:
        text = text.replace(
            "import logging\nfrom typing import TYPE_CHECKING\n",
            "import logging\nfrom datetime import datetime\nfrom typing import TYPE_CHECKING\nfrom zoneinfo import ZoneInfo\n",
            1,
        )
    text = text.replace(
        "sent = self._attendance_svc.send_due_group_attendance_prompts()\n",
        'now = datetime.now(ZoneInfo(self._timezone))\n            sent = self._attendance_svc.send_due_group_attendance_prompts(now)\n',
        1,
    )
    scheduler.write_text(text, encoding="utf-8")

    view_branch = '''elif action == "view":
        groups = repos.groups.get_by_coach(tg_id)
        if not groups:
            groups = repos.groups.get_active()
        if not groups:
            bot.answer_callback_query(call.id, "Групи не знайдено", show_alert=True)
            return
        group = groups[0]
        today = _date.today()
        summary = attendance_svc.get_attendance_summary(group.group_id, today)
        bot.edit_message_text(
            summary,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb.back_button("menu:attendance"),
        )

    '''
    text = bot.read_text(encoding="utf-8")
    if 'elif action == "view":' not in text:
        marker = 'elif action == "toggle":\n'
        if marker in text:
            text = text.replace(marker, view_branch + marker, 1)
            bot.write_text(text, encoding="utf-8")


def _apply_local_overrides() -> None:
    """
    If repository has local app/*.py files, overlay them on extracted runtime app.
    This lets us ship incremental improvements without rebuilding the zip archive.
    """
    if not LOCAL_APP_OVERRIDE.exists():
        return
    runtime_app_dir = APP_ROOT / "app"
    for src in LOCAL_APP_OVERRIDE.rglob("*.py"):
        if "__pycache__" in src.parts:
            continue
        rel = src.relative_to(LOCAL_APP_OVERRIDE)
        dst = runtime_app_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _materialize_google_credentials() -> None:
    """
    Railway does not include local files like credentials.json from a developer PC.
    If credentials are provided via env vars, write them to a local file and
    point GOOGLE_CREDENTIALS_FILE to that runtime path.
    """
    target = ROOT / "credentials.json"
    if target.exists():
        os.environ["GOOGLE_CREDENTIALS_FILE"] = str(target)
        _enable_real_data_mode()
        return

    json_env_names = (
        "GOOGLE_CREDENTIALS_JSON",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_APPLICATION_CREDENTIALS_JSON",
        "GCP_SERVICE_ACCOUNT_JSON",
    )
    b64_env_names = tuple(f"{name}_BASE64" for name in json_env_names) + (
        "GOOGLE_CREDENTIALS_JSON_BASE64",
    )
    file_env_names = ("GOOGLE_CREDENTIALS_FILE", "GOOGLE_APPLICATION_CREDENTIALS")

    payload_candidates: list[str] = []
    for env_name in b64_env_names:
        raw_b64 = os.getenv(env_name, "").strip()
        if not raw_b64:
            continue
        try:
            payload_candidates.append(
                base64.b64decode(raw_b64, validate=True).decode("utf-8")
            )
        except Exception:
            pass
    for env_name in json_env_names:
        raw_json = os.getenv(env_name, "").strip()
        if raw_json:
            payload_candidates.append(raw_json)
    for env_name in file_env_names:
        file_hint = os.getenv(env_name, "").strip()
        if file_hint.startswith("{"):
            payload_candidates.append(file_hint)

    fallback_payload = ""
    for payload in payload_candidates:
        try:
            parsed = json.loads(payload)
            target.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.environ["GOOGLE_CREDENTIALS_FILE"] = str(target)
            _enable_real_data_mode()
            return
        except Exception:
            fallback_payload = payload

    if fallback_payload:
        target.write_text(fallback_payload, encoding="utf-8")
        os.environ["GOOGLE_CREDENTIALS_FILE"] = str(target)
        _enable_real_data_mode()
        return

    for env_name in file_env_names:
        file_hint = os.getenv(env_name, "").strip()
        if not file_hint:
            continue
        hinted = Path(file_hint)
        if not hinted.is_absolute():
            hinted = ROOT / file_hint
        if hinted.exists():
            shutil.copy2(hinted, target)
            os.environ["GOOGLE_CREDENTIALS_FILE"] = str(target)
            _enable_real_data_mode()
            return

    if _running_on_railway():
        raise RuntimeError(
            "Google Sheets credentials are missing on Railway. "
            "Add GOOGLE_CREDENTIALS_JSON_BASE64 and redeploy; "
            "the bot will not use test data in production."
        )

    os.environ.setdefault("DRY_RUN", "true")


def main() -> None:
    _materialize_google_credentials()
    _ensure_runtime_app()
    _apply_hotfixes()
    _apply_local_overrides()
    sys.path.insert(0, str(APP_ROOT))
    runpy.run_module("app.main", run_name="__main__")


if __name__ == "__main__":
    main()
