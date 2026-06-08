"""
services/notifications.py — абстракція надсилання Telegram повідомлень.

Усі надсилання проходять через цей модуль, що дозволяє:
- логувати кожне відправлення
- безпечно обробляти помилки (chat not found, blocked, etc.)
- сегментно розсилати повідомлення (batch send)
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

import telebot

from app.models import ReminderLog, ReminderType
from app.repositories.base import IReminderLogRepository

log = logging.getLogger(__name__)

# Затримка між повідомленнями у batch-розсилці (секунди)
_BATCH_DELAY = 0.05


class NotificationService:
    """
    Сервіс надсилання Telegram повідомлень з логуванням і безпечною обробкою помилок.
    """

    def __init__(
        self,
        bot: telebot.TeleBot,
        reminder_log: IReminderLogRepository,
    ) -> None:
        self._bot = bot
        self._reminder_log = reminder_log

    def send(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup=None,
        *,
        reminder_type: Optional[ReminderType] = None,
        target_id: str = "",
    ) -> bool:
        """
        Надсилає одне повідомлення. Повертає True при успіху.
        Якщо задано reminder_type — логує у reminders_log.
        """
        try:
            self._bot.send_message(
                chat_id,
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            log.info("✉️ Надіслано → %s | %.60s…", chat_id, text.replace("\n", " "))

            if reminder_type:
                self._log_reminder(reminder_type, target_id, chat_id, text)

            return True

        except telebot.apihelper.ApiTelegramException as e:
            if "bot was blocked by the user" in str(e):
                log.warning("Бот заблокований користувачем %s", chat_id)
            elif "chat not found" in str(e):
                log.warning("Чат не знайдено: %s", chat_id)
            else:
                log.error("Telegram API помилка для %s: %s", chat_id, e)
            return False
        except Exception as e:
            log.error("Невідома помилка при надсиланні до %s: %s", chat_id, e)
            return False

    def send_batch(
        self,
        recipients: List[int],
        text: str,
        parse_mode: str = "HTML",
        reply_markup=None,
        *,
        reminder_type: Optional[ReminderType] = None,
        target_id: str = "",
    ) -> dict[int, bool]:
        """
        Надсилає одне повідомлення кільком отримувачам.
        Повертає dict {chat_id: success}.
        """
        results: dict[int, bool] = {}
        for chat_id in recipients:
            results[chat_id] = self.send(
                chat_id,
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                reminder_type=reminder_type,
                target_id=target_id,
            )
            time.sleep(_BATCH_DELAY)
        return results

    def send_to_owner(
        self,
        owner_chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup=None,
    ) -> bool:
        """Зручний метод для надсилання власнику."""
        return self.send(owner_chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)

    def answer_callback(self, call: telebot.types.CallbackQuery,
                        text: str, show_alert: bool = False) -> None:
        """Безпечно відповідає на callback query."""
        try:
            self._bot.answer_callback_query(call.id, text, show_alert=show_alert)
        except Exception as e:
            log.warning("answer_callback помилка: %s", e)

    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup=None,
    ) -> bool:
        """Редагує існуюче повідомлення."""
        try:
            self._bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            return True
        except Exception as e:
            log.warning("edit_message помилка: %s", e)
            return False

    def _log_reminder(
        self,
        reminder_type: ReminderType,
        target_id: str,
        chat_id: int,
        text: str,
    ) -> None:
        """Записує нагадування у reminders_log (ігнорує помилки запису)."""
        try:
            import uuid
            from datetime import datetime
            from app.models import ReminderLog
            entry = ReminderLog(
                log_id=str(uuid.uuid4())[:8],
                reminder_type=reminder_type,
                target_id=target_id,
                sent_to=chat_id,
                sent_at=datetime.now(),
                message_preview=text[:200],
            )
            self._reminder_log.add(entry)
        except Exception as e:
            log.warning("Помилка запису до reminders_log: %s", e)
