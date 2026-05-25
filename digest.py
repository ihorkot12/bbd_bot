"""
services/templates.py — шаблони повідомлень з дефолтами українською мовою.

Шаблони зберігаються у Google Sheets (message_templates).
Якщо шаблон відсутній у Sheets — повертається вбудований дефолт.
Підтримує змінні у форматі {variable_name}.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from app.models import MessageTemplate
from app.repositories.base import IMessageTemplateRepository

log = logging.getLogger(__name__)

# ── Вбудовані шаблони (дефолти) ───────────────────────────────────────────────

DEFAULT_TEMPLATES: Dict[str, str] = {
    # Оплата
    "payment_reminder": (
        "👋 Вітаємо, <b>{parent_name}</b>!\n\n"
        "Нагадуємо, що оплата за тренування у <b>Black Bear Dojo</b> "
        "за <b>{period}</b> ще не надійшла.\n\n"
        "💰 Сума: <b>{amount_due} грн</b>\n"
        "Статус: <b>{status}</b>\n\n"
        "Якщо оплата вже здійснена — повідомте тренера або адміністратора.\n"
        "Дякуємо! 🥋"
    ),
    "payment_overdue": (
        "⚠️ <b>Прострочена оплата!</b>\n\n"
        "Шановний/а <b>{parent_name}</b>,\n"
        "Оплата за <b>{period}</b> прострочена!\n\n"
        "💰 Сума: <b>{amount_due} грн</b>\n"
        "Сплачено: <b>{amount_paid} грн</b>\n\n"
        "Будь ласка, зверніться до адміністратора."
    ),
    "payment_partial": (
        "💛 <b>Часткова оплата</b>\n\n"
        "Привіт, <b>{parent_name}</b>!\n"
        "За <b>{period}</b> отримано часткову оплату.\n\n"
        "💰 До сплати: <b>{amount_due} грн</b>\n"
        "Сплачено: <b>{amount_paid} грн</b>\n"
        "Залишок: <b>{balance} грн</b>"
    ),

    # Проб'ні / ліди
    "trial_confirmation": (
        "🎉 <b>Ваше пробне тренування заплановано!</b>\n\n"
        "Дитина: <b>{child_name}</b>\n"
        "📅 Дата: <b>{trial_date}</b>\n"
        "📍 Адреса: <b>{address}</b>\n"
        "⏰ Розклад групи: <b>{schedule}</b>\n\n"
        "👕 Що взяти:\n"
        "• Зручний спортивний одяг\n"
        "• Змінне взуття\n"
        "• Пляшку з водою\n\n"
        "Будемо раді вас бачити! 🥋\n"
        "З питань: {phone}"
    ),
    "trial_reminder": (
        "⏰ <b>Нагадування про пробне тренування!</b>\n\n"
        "Завтра пробне тренування для <b>{child_name}</b>.\n"
        "📅 Дата: <b>{trial_date}</b>\n"
        "📍 Адреса: <b>{address}</b>\n\n"
        "Якщо плани змінились — будь ласка, повідомте заздалегідь."
    ),
    "trial_day_reminder": (
        "🥋 <b>Сьогодні пробне тренування!</b>\n\n"
        "Нагадуємо: сьогодні пробне для <b>{child_name}</b>.\n"
        "📍 <b>{address}</b>\n\n"
        "Чекаємо на вас!"
    ),
    "after_trial_owner": (
        "📋 <b>Пробне тренування завершено</b>\n\n"
        "Дитина: <b>{child_name}</b>\n"
        "Батьки: <b>{parent_name}</b>\n"
        "📅 Дата: <b>{trial_date}</b>\n\n"
        "Будь ласка, вкажіть результат:"
    ),

    # Відвідуваність
    "attendance_coach_reminder": (
        "📋 <b>Нагадування про журнал!</b>\n\n"
        "Тренування групи <b>{group_name}</b> сьогодні.\n"
        "Будь ласка, відмітьте відвідуваність після заняття."
    ),
    "attendance_unclosed_alert": (
        "⚠️ <b>Незакритий журнал!</b>\n\n"
        "Група: <b>{group_name}</b>\n"
        "Дата: <b>{lesson_date}</b>\n\n"
        "Тренер <b>{coach_name}</b> не закрив журнал відвідуваності.\n"
        "Будь ласка, перевірте."
    ),
    "inactivity_7_days": (
        "😟 <b>Дитина не відвідує тренування!</b>\n\n"
        "<b>{child_name}</b> відсутній/відсутня вже <b>7 днів</b>.\n"
        "Рекомендуємо зв'язатися з батьками."
    ),
    "inactivity_14_days": (
        "⚠️ <b>Тривала відсутність!</b>\n\n"
        "<b>{child_name}</b> відсутній/відсутня вже <b>14 днів</b>.\n"
        "Ризик відтоку — необхідний контакт з батьками."
    ),
    "inactivity_21_days": (
        "🔴 <b>КРИТИЧНА ВІДСУТНІСТЬ!</b>\n\n"
        "<b>{child_name}</b> відсутній/відсутня вже <b>21 день</b>.\n"
        "Терміново зв'яжіться з сім'єю!"
    ),

    # Клубна інформація
    "info_address": (
        "📍 <b>Адреса Black Bear Dojo:</b>\n\n"
        "{address}\n\n"
        "🗺 <a href=\"{maps_link}\">Відкрити на карті</a>"
    ),
    "info_schedule": (
        "📅 <b>Розклад тренувань:</b>\n\n"
        "{schedule_text}\n\n"
        "З питань: {phone}"
    ),
    "info_price": (
        "💰 <b>Вартість занять:</b>\n\n"
        "{price_text}\n\n"
        "З питань: {phone}"
    ),
    "info_contact": (
        "📞 <b>Контакти Black Bear Dojo:</b>\n\n"
        "📱 Телефон: {phone}\n"
        "📍 Адреса: {address}\n"
        "🌐 Сайт: {website}"
    ),
    "info_first_visit": (
        "👋 <b>Ласкаво просимо до Black Bear Dojo!</b>\n\n"
        "Ми раді вас вітати! Ось що вам потрібно знати перед першим відвідуванням:\n\n"
        "📍 Адреса: {address}\n"
        "⏰ Ваше перше тренування: {trial_date}\n"
        "👕 Одяг: зручний спортивний одяг, змінне взуття\n"
        "💧 Візьміть пляшку з водою\n\n"
        "Будь-які питання: {phone}\n\n"
        "🥋 Зустрінемося на татамі!"
    ),

    # Події
    "event_announcement": (
        "📣 <b>Анонс події!</b>\n\n"
        "🎯 <b>{title}</b>\n"
        "📅 Дата: <b>{event_date}</b>\n\n"
        "{description}\n\n"
        "Слідкуйте за оновленнями! 🥋"
    ),
    "event_reminder": (
        "⏰ <b>Нагадування про подію!</b>\n\n"
        "Незабаром: <b>{title}</b>\n"
        "📅 {event_date}\n\n"
        "{description}"
    ),

    # Дні народження
    "birthday_channel_post": (
        "🎂 Вітаємо <b>{public_name}</b> з днем народження!\n\n"
        "Бажаємо здоровʼя, сили, дисципліни, сміливості та нових перемог на татамі.\n"
        "Нехай кожне тренування у <b>{club_name}</b> робить тебе сильнішим/сильнішою 🥋"
    ),

    # Дайджест
    "daily_digest_header": (
        "📊 <b>Щоденний дайджест Black Bear Dojo</b>\n"
        "📅 {date}\n"
        "{'─' * 30}"
    ),
}


class TemplateService:
    """
    Завантажує шаблони з репозиторію; повертає вбудований дефолт якщо не знайдено.
    """

    def __init__(self, repo: IMessageTemplateRepository) -> None:
        self._repo = repo
        self._cache: Dict[str, str] = {}

    def get(self, name: str) -> str:
        """Повертає текст шаблону (з кешу, Sheets або дефолт)."""
        if name in self._cache:
            return self._cache[name]

        try:
            tmpl = self._repo.get_by_name(name)
            if tmpl and tmpl.text.strip():
                self._cache[name] = tmpl.text
                return tmpl.text
        except Exception as e:
            log.warning("Не вдалося завантажити шаблон '%s' з Sheets: %s", name, e)

        default = DEFAULT_TEMPLATES.get(name, "")
        if not default:
            log.warning("Шаблон '%s' не знайдено (ані в Sheets, ані в дефолтах)", name)
        return default

    def render(self, name: str, **kwargs) -> str:
        """Рендерить шаблон із змінними."""
        template_text = self.get(name)
        if not template_text:
            return f"[Шаблон '{name}' не знайдено]"
        try:
            return template_text.format(**kwargs)
        except KeyError as e:
            log.error("Відсутня змінна %s у шаблоні '%s'", e, name)
            return template_text  # повертаємо нерендерений текст
        except Exception as e:
            log.error("Помилка рендеру шаблону '%s': %s", name, e)
            return template_text

    def seed_defaults(self) -> int:
        """
        Записує всі вбудовані дефолти у Sheets (тільки якщо запису ще нема).
        Повертає кількість доданих шаблонів.
        """
        count = 0
        for name, text in DEFAULT_TEMPLATES.items():
            try:
                existing = self._repo.get_by_name(name)
                if not existing:
                    import uuid
                    self._repo.upsert(MessageTemplate(
                        template_id=str(uuid.uuid4())[:8],
                        name=name,
                        text=text,
                        variables=None,
                    ))
                    count += 1
            except Exception as e:
                log.warning("Помилка seed шаблону '%s': %s", name, e)
        log.info("Засіяно %d шаблонів у Sheets", count)
        return count

    def invalidate_cache(self) -> None:
        """Скидає локальний кеш (для оновлення шаблонів без перезапуску)."""
        self._cache.clear()

    def list_names(self) -> list:
        """Повертає список усіх імен шаблонів (Sheets + дефолти)."""
        names = set(DEFAULT_TEMPLATES.keys())
        try:
            for t in self._repo.get_all():
                names.add(t.name)
        except Exception:
            pass
        return sorted(names)
