# 🐻 Black Bear Dojo Bot V2

Операційний Telegram-бот для клубу **Black Bear Dojo** (Київ, Україна).

> **Мова інтерфейсу:** Українська  
> **Стек:** Python 3.11 · pyTelegramBotAPI · Google Sheets API · APScheduler

---

## Що вміє бот

| Модуль | Функціонал |
|---|---|
| 💰 **Оплати** | Статуси (paid/partial/unpaid/promised/overdue/frozen), нагадування у дні 1/5/10, список боржників, перехід у overdue |
| 📋 **Відвідуваність** | Нагадування тренеру, позначення присутності/відсутності, алерт власнику при незакритому журналі, виявлення неактивних (7/14/21 день) |
| 🔍 **Ліди / Проби** | Реєстрація через бот або Google Form, нагадування батькам, рішення після проби, конвертація у учня |
| 👥 **Учасники** | Діти (child) та дорослі (adult), дані батьків опціональні для дорослих |
| 📅 **Події** | Створення, анонс аудиторії, автоматичні нагадування |
| 📊 **Дайджест** | Щоденний звіт власнику о 08:00 (ліди, оплати, відвідуваність, події) |
| ✉️ **Шаблони** | Українські шаблони у Google Sheets, редаговані без перезапуску |
| ⚙️ **Ролі** | guest / lead / parent / coach / admin / owner з ієрархією прав |

---

## Реальна Google-інфраструктура

| Ресурс | Посилання |
|---|---|
| 📊 Google Sheets | [Таблиця Black Bear Dojo](https://docs.google.com/spreadsheets/d/101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg/edit) |
| 📝 Повна реєстрація | [Форма учасника / сімʼї](https://docs.google.com/forms/d/e/1FAIpQLSesT2y1vreDee-V90xP66GaTEPFibCXuGI9czsOK6iqg0HpYA/viewform) |
| 🥋 Пробне тренування | [Коротка форма пробного](https://docs.google.com/forms/d/e/1FAIpQLSc7hWokYpbwC8JnY-VlHgwEcJGsOPBz-xf0aQeepQDWMwHkMA/viewform) |

---

## Швидкий старт

### 1. Клонування і середовище

```bash
git clone <repo>
cd black-bear-dojo-bot-v2
python3.11 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# або .venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 2. Конфігурація `.env`

```bash
cp .env.example .env
nano .env   # або відкрийте у будь-якому редакторі
```

**Обов'язкові поля:**

```
TELEGRAM_BOT_TOKEN=         ← токен від @BotFather (НЕ вставляти у код!)
OWNER_TELEGRAM_ID=329214126 ← вже заповнено
GOOGLE_CREDENTIALS_FILE=credentials.json
SPREADSHEET_ID=101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg   ← вже заповнено
REGISTRATION_FORM_ID=1rdsZwpIY93fdXtd5e8-hnfn9Si7bt0fNtmKlfLlZCO8  ← вже заповнено
TIMEZONE=Europe/Kyiv
```

### 3. Налаштування Google Service Account

1. Відкрийте [Google Cloud Console](https://console.cloud.google.com/)
2. Створіть або виберіть проєкт
3. Увімкніть APIs:
   - **Google Sheets API**
   - **Google Drive API**
   - **Google Forms API** (опціонально — для polling форми через API)
4. Створіть **Service Account** (IAM & Admin → Service Accounts)
5. Завантажте JSON-ключ → збережіть як `credentials.json` у корені проекту
6. **Надайте доступ Service Account до таблиці:**
   - Відкрийте [таблицю](https://docs.google.com/spreadsheets/d/101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg/edit)
   - Поділитися → додайте email Service Account як **Редактор**

### 4. Bootstrap таблиці (перший запуск)

```bash
python scripts/bootstrap_sheets.py
```

Скрипт:
- Перевіряє всі аркуші (users_roles, members, payments, groups, attendance, leads, events, message_templates, tasks, reminders_log, audit_log, announcements, settings, form_responses)
- Додає відсутні заголовки
- Засіює налаштування та шаблони повідомлень
- Додає власника (ID 329214126) до users_roles з роллю owner

```bash
# Тільки перевірити, нічого не записувати:
python scripts/bootstrap_sheets.py --dry-run

# Інший spreadsheet:
python scripts/bootstrap_sheets.py --spreadsheet-id YOUR_ID
```

### 5. Запуск бота

```bash
python -m app.main
```

---

## ✅ Чеклист запуску в продакшн

- [ ] **Токен бота** отримано від @BotFather і записано у `.env` → `TELEGRAM_BOT_TOKEN`
- [ ] **`credentials.json`** скачано з Google Cloud Console (Service Account → JSON key)
- [ ] **Service Account** має права Редактора на [таблицю Google Sheets](https://docs.google.com/spreadsheets/d/101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg/edit)
- [ ] **`OWNER_TELEGRAM_ID=329214126`** підтверджено у `.env`
- [ ] **`SPREADSHEET_ID`** перевірено: `101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg`
- [ ] **`TIMEZONE=Europe/Kyiv`** встановлено у `.env`
- [ ] **Bootstrap виконано:** `python scripts/bootstrap_sheets.py`
- [ ] **Тести пройшли:** `pytest tests/ -v`
- [ ] **Бот запускається:** `python -m app.main` (перевірте `/start` у Telegram)
- [ ] **Власник отримує дайджест** о 08:00 (або надішліть `/digest`)
- [ ] **Hosting 24/7** налаштовано (systemd, Docker, Railway, VPS):
  - VPS / сервер: `systemctl enable bbd-bot && systemctl start bbd-bot`
  - Docker: `docker-compose up -d` (додайте `Dockerfile` за потреби)
  - Railway / Render: додайте `Procfile` або `Dockerfile`
- [ ] **Адміністраторів / тренерів** додано у таблицю `users_roles` з відповідними ролями
- [ ] **Google Form** прив'язана до аркуша `form_responses` (якщо використовується polling через Sheets):
  - Відкрийте форму → Відповіді → Таблиця → вибрати існуючу таблицю → `form_responses`
- [ ] **Інформацію про клуб** заповнено у `.env`: `CLUB_ADDRESS`, `CLUB_PHONE`, `CLUB_SCHEDULE_TEXT`, `CLUB_PRICE_TEXT`

---

## Hosting 24/7 (приклад systemd)

Збережіть як `/etc/systemd/system/bbd-bot.service`:

```ini
[Unit]
Description=Black Bear Dojo Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/black-bear-dojo-bot-v2
EnvironmentFile=/home/ubuntu/black-bear-dojo-bot-v2/.env
ExecStart=/home/ubuntu/black-bear-dojo-bot-v2/.venv/bin/python -m app.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable bbd-bot
sudo systemctl start bbd-bot
sudo journalctl -u bbd-bot -f   # перегляд логів
```

---

## Реєстрація через Google Form

Форма для реєстрації нових учасників:
🔗 [https://docs.google.com/forms/d/e/1FAIpQLSesT2y1vreDee-V90xP66GaTEPFibCXuGI9czsOK6iqg0HpYA/viewform](https://docs.google.com/forms/d/e/1FAIpQLSesT2y1vreDee-V90xP66GaTEPFibCXuGI9czsOK6iqg0HpYA/viewform)

**Як налаштувати автоматичну обробку відповідей:**
1. Відкрийте форму → вкладка "Відповіді"
2. Натисніть іконку Google Sheets → "Вибрати існуючу таблицю"
3. Виберіть таблицю **Black Bear Dojo — База даних бота V2**
4. Вкажіть аркуш: **form_responses**
5. Бот автоматично опитує цей аркуш кожні `FORM_POLL_INTERVAL_MINUTES` хвилин

---

## Структура проекту

```
black-bear-dojo-bot-v2/
├── app/
│   ├── main.py              # точка входу
│   ├── config.py            # .env конфігурація
│   ├── bot.py               # хендлери Telegram
│   ├── keyboards.py         # клавіатури (Ukrainian UI)
│   ├── access.py            # ролі та дозволи
│   ├── models.py            # dataclasses + enums
│   ├── logging_setup.py     # налаштування логування
│   ├── scheduler.py         # APScheduler задачі
│   ├── repositories/
│   │   ├── base.py          # Protocol інтерфейси
│   │   ├── google_sheets.py # Google Sheets gateway
│   │   └── stub.py          # in-memory для тестів
│   └── services/
│       ├── payments.py      # оплати
│       ├── attendance.py    # відвідуваність
│       ├── leads.py         # ліди / проби
│       ├── events.py        # події
│       ├── templates.py     # шаблони повідомлень
│       ├── digest.py        # щоденний дайджест
│       ├── notifications.py # надсилання Telegram
│       └── form_poller.py   # опитування Google Form
├── tests/
│   ├── test_payments.py
│   ├── test_access.py
│   ├── test_models.py
│   ├── test_templates.py
│   ├── test_attendance.py
│   ├── test_leads.py
│   └── test_digest.py
├── scripts/
│   └── bootstrap_sheets.py  # ініціалізація Sheets
├── .env.example             # шаблон конфігурації
├── .gitignore
└── requirements.txt
```

---

## Аркуші Google Sheets

| Аркуш | Призначення |
|---|---|
| `users_roles` | Telegram ID → роль (guest/lead/parent/coach/admin/owner) |
| `members` | Учасники клубу (child та adult) |
| `payments` | Оплати по місяцях |
| `groups` | Групи з розкладом та тренерами |
| `attendance` | Журнал відвідуваності |
| `leads` | Ліди та пробні тренування |
| `events` | Клубні події |
| `message_templates` | Шаблони повідомлень (редагуються без коду) |
| `tasks` | Завдання персоналу |
| `reminders_log` | Лог надісланих нагадувань |
| `audit_log` | Аудит дій |
| `announcements` | Оголошення |
| `settings` | Налаштування клубу |
| `form_responses` | Відповіді Google Form (для polling) |

---

## Тести

```bash
# Запуск всіх тестів (без credentials!)
pytest tests/ -v

# З покриттям
pytest tests/ --cov=app --cov-report=term-missing

# Один файл
pytest tests/test_payments.py -v
```

Тести **не** потребують реального Telegram-токену або Google credentials.

---

## Змінні середовища — повний список

| Змінна | Обов'язкова | Значення за замовчуванням | Опис |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Токен від @BotFather |
| `OWNER_TELEGRAM_ID` | ✅ | `329214126` | Telegram ID власника |
| `GOOGLE_CREDENTIALS_FILE` | ✅ | `credentials.json` | Шлях до Service Account JSON |
| `SPREADSHEET_ID` | ✅ | `101vNE0kgiKy-WfqYOKpjrgcWVtYtuceDP3xTAK9Mlrg` | ID таблиці |
| `REGISTRATION_FORM_ID` | — | `1rdsZwpIY93fdXtd5e8-hnfn9Si7bt0fNtmKlfLlZCO8` | ID Google Form |
| `REGISTRATION_FORM_URL` | — | *(посилання на форму)* | URL форми для відображення |
| `FORM_POLL_INTERVAL_MINUTES` | — | `30` | Інтервал опитування форми |
| `PAYMENT_REMINDER_DAYS` | — | `1,5,10` | Дні місяця для нагадувань |
| `ATTENDANCE_REMINDER_TIME` | — | `09:00` | Час нагадування тренерам |
| `ATTENDANCE_DEADLINE_TIME` | — | `22:00` | Час перевірки незакритих журналів |
| `DIGEST_TIME` | — | `08:00` | Час щоденного дайджесту |
| `TIMEZONE` | — | `Europe/Kyiv` | Часовий пояс |
| `CLUB_NAME` | — | `Black Bear Dojo` | Назва клубу |
| `CLUB_ADDRESS` | — | *(адреса)* | Адреса для відображення |
| `CLUB_PHONE` | — | *(телефон)* | Телефон для відображення |
| `LOG_LEVEL` | — | `INFO` | Рівень логування |
| `LOG_FILE` | — | *(порожньо)* | Шлях до файлу логів |
| `DRY_RUN` | — | `false` | `true` → без Google Sheets (для тестів) |

---

*Black Bear Dojo Bot V2 — зроблено для реальної роботи клубу, не просто як демо.*
