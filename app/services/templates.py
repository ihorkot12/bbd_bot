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
    "birthday_channel_post_warm": (
        "🎂 Сьогодні особливий день у нашій команді!\n\n"
        "Вітаємо <b>{public_name}</b> з днем народження. Бажаємо міцного здоровʼя, "
        "радості, сміливості, гарних друзів поруч і багато нових маленьких перемог.\n\n"
        "Нехай у <b>{club_name}</b> завжди буде місце для розвитку, підтримки і впевненості. "
        "Зі святом! 🥋"
    ),
    "birthday_channel_post_champion": (
        "🥋 <b>{public_name}</b>, з днем народження!\n\n"
        "Бажаємо характеру чемпіона, спокою в голові, сили в тілі та віри у себе. "
        "Нехай кожне тренування додає впевненості, а кожен новий пояс стає чесним результатом праці.\n\n"
        "<b>{club_name}</b> пишається тобою. Осу!"
    ),
    "birthday_channel_post_short": (
        "🎂 Вітаємо <b>{public_name}</b> з днем народження!\n\n"
        "Бажаємо здоровʼя, радості, дисципліни, сміливості та нових перемог на татамі. "
        "Осу від <b>{club_name}</b> 🥋"
    ),
    "birthday_private_parent": (
        "👋 Вітаємо!\n\n"
        "Сьогодні день народження у <b>{child_name}</b>. Від усієї команди <b>{club_name}</b> "
        "бажаємо здоровʼя, радості, впевненості та гарного спортивного року.\n\n"
        "Дякуємо, що ви з нами 🥋"
    ),
    "birthday_moderation_note": (
        "🎂 <b>Привітання на модерацію</b>\n\n"
        "У <b>{public_name}</b> сьогодні день народження.\n"
        "Перевірте текст нижче і натисніть кнопку публікації, якщо все ок.\n\n"
        "{birthday_text}"
    ),

    # Повідомлення батькам / повернення після пропусків
    "parent_absence_followup": (
        "👋 Доброго дня!\n\n"
        "Бачимо кілька пропусків у <b>{child_name}</b> на тренуваннях {group_name}.\n\n"
        "Якщо є пауза, хвороба або зміни в графіку — просто дайте знати тренеру. "
        "Так ми коректно плануємо групу і не втрачаємо контакт з дитиною.\n\n"
        "Дякуємо 🥋"
    ),
    "parent_absence_soft": (
        "👋 Доброго дня!\n\n"
        "<b>{child_name}</b> давно не був/була на тренуванні, тому хочемо акуратно уточнити: "
        "у вас все в силі з відвідуванням <b>{club_name}</b>?\n\n"
        "Якщо потрібна пауза або інший графік — напишіть, будь ласка. Допоможемо підібрати зручний варіант."
    ),
    "parent_absence_return": (
        "🥋 Раді будемо бачити <b>{child_name}</b> на тренуванні знову!\n\n"
        "Після паузи можна просто прийти у свою групу. Тренер допоможе спокійно повернутись у ритм, "
        "без зайвого тиску.\n\n"
        "Якщо хочете уточнити день або час — напишіть нам."
    ),
    "parent_after_trial_thanks": (
        "👋 Дякуємо, що були на пробному тренуванні у <b>{club_name}</b>!\n\n"
        "Якщо дитині сподобалось, можемо одразу підказати групу, графік і наступний крок для старту. "
        "Якщо залишились питання — напишіть, ми все пояснимо спокійно і по суті 🥋"
    ),
    "parent_trial_no_show": (
        "👋 Доброго дня!\n\n"
        "Сьогодні ви не змогли прийти на пробне тренування для <b>{child_name}</b>. "
        "Нічого страшного, так буває.\n\n"
        "Якщо хочете, підберемо інший день для пробного заняття."
    ),
    "parent_schedule_change": (
        "📅 <b>Оновлення по розкладу</b>\n\n"
        "Група: <b>{group_name}</b>\n"
        "Зміна: {change_text}\n\n"
        "Якщо цей час вам не підходить — напишіть, підберемо варіант."
    ),

    # Готові пости для каналу / соцмереж
    "club_post_open_join": (
        "🥋 <b>Black Bear Dojo набирає учасників у групи карате</b>\n\n"
        "Запрошуємо дітей на тренування з кіокушинкай карате. На заняттях працюємо над дисципліною, "
        "координацією, силою, витривалістю та впевненістю.\n\n"
        "Пробне тренування допоможе зрозуміти, чи підходить дитині формат групи.\n\n"
        "📍 {address}\n"
        "📞 {phone}"
    ),
    "club_post_new_group": (
        "📣 <b>Відкриваємо набір у нову групу</b>\n\n"
        "Група: <b>{group_name}</b>\n"
        "Розклад: <b>{schedule}</b>\n\n"
        "Запрошуємо дітей, які хочуть тренуватись, ставати сильнішими і впевненішими. "
        "Кількість місць у групі обмежена, щоб тренер міг приділити увагу кожному.\n\n"
        "Для запису на пробне тренування напишіть нам."
    ),
    "club_post_exam_congrats": (
        "🥋 <b>Вітаємо з атестацією!</b>\n\n"
        "Сьогодні наші учасники зробили ще один крок у карате. Атестація — це не просто пояс, "
        "а результат регулярності, дисципліни і характеру.\n\n"
        "Пишаємось кожним, хто вийшов на татамі і показав свою роботу. Осу!"
    ),
    "club_post_competition_congrats": (
        "🏆 <b>Вітаємо команду Black Bear Dojo!</b>\n\n"
        "Змагання — це завжди досвід, характер і чесна перевірка себе. Дякуємо спортсменам за сміливість, "
        "батькам за підтримку, тренерам за підготовку.\n\n"
        "Працюємо далі. Осу!"
    ),
    "club_post_photo_day": (
        "📸 <b>День фото/відео у клубі</b>\n\n"
        "На найближчому тренуванні плануємо зробити кілька фото та відео для клубного архіву і соцмереж.\n\n"
        "Якщо ви не даєте згоду на публікацію фото/відео дитини — напишіть тренеру заздалегідь."
    ),
    "club_post_parent_thanks": (
        "🤝 Дякуємо батькам за довіру і підтримку.\n\n"
        "Регулярні тренування дітей — це завжди командна робота: дитина, тренер і сімʼя. "
        "Коли вдома підтримують режим, а в залі є дисципліна, прогрес приходить швидше.\n\n"
        "Дякуємо, що ви з <b>{club_name}</b> 🥋"
    ),
    "club_post_training_reminder": (
        "🥋 <b>Нагадування про тренування</b>\n\n"
        "Сьогодні тренування групи <b>{group_name}</b>.\n"
        "Час: <b>{time}</b>\n\n"
        "Візьміть форму/зручний одяг, воду і гарний настрій. До зустрічі в залі!"
    ),
    "club_post_holiday_greeting": (
        "✨ <b>{holiday_name}</b>\n\n"
        "Команда <b>{club_name}</b> вітає нашу клубну родину зі святом. "
        "Бажаємо здоровʼя, сили, спокою і тепла поруч.\n\n"
        "Дякуємо, що продовжуємо тренуватись, підтримувати дітей і рухатись вперед разом."
    ),

    # Дайджест
    "daily_digest_header": (
        "📊 <b>Щоденний дайджест Black Bear Dojo</b>\n"
        "📅 {date}\n"
        "{'─' * 30}"
    ),
}

TEMPLATE_CATEGORIES: Dict[str, tuple[str, ...]] = {
    "Оплата": (
        "payment_reminder",
        "payment_overdue",
        "payment_partial",
    ),
    "Пробні тренування": (
        "trial_confirmation",
        "trial_reminder",
        "trial_day_reminder",
        "after_trial_owner",
        "parent_after_trial_thanks",
        "parent_trial_no_show",
    ),
    "Відвідуваність": (
        "attendance_coach_reminder",
        "attendance_unclosed_alert",
        "parent_absence_followup",
        "parent_absence_soft",
        "parent_absence_return",
        "inactivity_7_days",
        "inactivity_14_days",
        "inactivity_21_days",
    ),
    "Дні народження": (
        "birthday_channel_post",
        "birthday_channel_post_warm",
        "birthday_channel_post_champion",
        "birthday_channel_post_short",
        "birthday_private_parent",
        "birthday_moderation_note",
    ),
    "Інформація клубу": (
        "info_address",
        "info_schedule",
        "info_price",
        "info_contact",
        "info_first_visit",
        "parent_schedule_change",
    ),
    "Пости для каналу": (
        "club_post_open_join",
        "club_post_new_group",
        "club_post_exam_congrats",
        "club_post_competition_congrats",
        "club_post_photo_day",
        "club_post_parent_thanks",
        "club_post_training_reminder",
        "club_post_holiday_greeting",
        "event_announcement",
        "event_reminder",
    ),
    "Службові": (
        "daily_digest_header",
    ),
}


TEMPLATE_VARIABLES: Dict[str, tuple[str, ...]] = {
    "payment_reminder": ("parent_name", "period", "amount_due", "status"),
    "payment_overdue": ("parent_name", "period", "amount_due", "amount_paid"),
    "payment_partial": ("parent_name", "period", "amount_due", "amount_paid", "balance"),
    "trial_confirmation": ("child_name", "parent_name", "trial_date", "address", "schedule", "phone"),
    "trial_reminder": ("child_name", "trial_date", "address"),
    "trial_day_reminder": ("child_name", "address"),
    "after_trial_owner": ("child_name", "parent_name", "trial_date"),
    "attendance_coach_reminder": ("group_name",),
    "attendance_unclosed_alert": ("group_name", "lesson_date", "coach_name"),
    "inactivity_7_days": ("child_name", "days"),
    "inactivity_14_days": ("child_name", "days"),
    "inactivity_21_days": ("child_name", "days"),
    "info_address": ("address", "maps_link"),
    "info_schedule": ("schedule_text", "phone"),
    "info_price": ("price_text", "phone"),
    "info_contact": ("phone", "address", "website"),
    "info_first_visit": ("address", "trial_date", "phone"),
    "event_announcement": ("title", "event_date", "description"),
    "event_reminder": ("title", "event_date", "description"),
    "birthday_channel_post": ("public_name", "club_name"),
    "birthday_channel_post_warm": ("public_name", "club_name"),
    "birthday_channel_post_champion": ("public_name", "club_name"),
    "birthday_channel_post_short": ("public_name", "club_name"),
    "birthday_private_parent": ("child_name", "club_name"),
    "birthday_moderation_note": ("public_name", "birthday_text"),
    "parent_absence_followup": ("child_name", "group_name"),
    "parent_absence_soft": ("child_name", "club_name"),
    "parent_absence_return": ("child_name",),
    "parent_after_trial_thanks": ("club_name",),
    "parent_trial_no_show": ("child_name",),
    "parent_schedule_change": ("group_name", "change_text"),
    "club_post_open_join": ("address", "phone"),
    "club_post_new_group": ("group_name", "schedule"),
    "club_post_parent_thanks": ("club_name",),
    "club_post_training_reminder": ("group_name", "time"),
    "club_post_holiday_greeting": ("holiday_name", "club_name"),
    "daily_digest_header": ("date",),
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
        try:
            existing_names = {template.name for template in self._repo.get_all()}
        except Exception as e:
            log.warning("Не вдалося прочитати існуючі шаблони перед seed: %s", e)
            return 0

        new_templates: list[MessageTemplate] = []
        for name, text in DEFAULT_TEMPLATES.items():
            if name in existing_names:
                continue
            import uuid
            new_templates.append(MessageTemplate(
                template_id=str(uuid.uuid4())[:8],
                name=name,
                text=text,
                variables=", ".join(TEMPLATE_VARIABLES.get(name, ())) or None,
            ))

        append_many = getattr(self._repo, "append_many", None)
        if append_many:
            append_many(new_templates)
        else:
            for template in new_templates:
                self._repo.upsert(template)

        count = len(new_templates)
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

    def categories(self) -> Dict[str, tuple[str, ...]]:
        """Повертає категорії дефолтних шаблонів для зручного перегляду в боті."""
        return TEMPLATE_CATEGORIES

    def variables_for(self, name: str) -> tuple[str, ...]:
        """Повертає змінні, які очікує шаблон."""
        return TEMPLATE_VARIABLES.get(name, ())
