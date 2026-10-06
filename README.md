<h1 align="center">🏆 Dota Party Tracker</h1>

<p align="center">
  <b>Telegram-бот для пати: рейтинг, MMR и статистика ранкед-игр Dota 2.</b><br>
  Данные — из <a href="https://www.opendota.com/">OpenDota</a>.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/aiogram-3.13-2CA5E0?logo=telegram&logoColor=white" alt="aiogram">
  <img src="https://img.shields.io/badge/data-OpenDota-E4342B" alt="OpenDota">
  <img src="https://img.shields.io/badge/DB-SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite">
</p>

---

## Что это

Добавьте бота в чат пати и игроков через `/add`. Дальше бот сам считает ранкед-игры и ведёт общий рейтинг: оценку MMR, серии, винрейт, KDA, награды, совместные игры, карточки игроков. Раз в день присылает сводку.

## Про MMR

Точный MMR Dota 2 не отдаёт ни один публичный API, поэтому бот его **оценивает**:

```
MMR ≈ стартовый MMR + (победы − поражения) × шаг      (шаг по умолчанию 25)
```

Стартовый MMR вводите вы: в `/add` или через `/setmmr`. Оценка везде помечена знаком `≈`. Ранг, число игр, KDA, винрейт, герои и GPM — настоящие данные.

> Бот видит матчи, только если в Dota 2 включена опция **«Выставлять публичные данные матчей»** (Настройки → Социальные). Игры, сыгранные до включения, не подтянутся.

---

## Быстрый старт

Нужны Python 3.12+ и токен бота от [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/adxptived/dota-party-tracker.git
cd dota-party-tracker

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env        # впишите BOT_TOKEN
python -m mmrbot
```

Бот работает по long-polling: процесс должен оставаться запущенным. Остановка — `Ctrl+C`.

`STRATZ_API_KEY` в `.env` необязателен. С ним появляются позиции, роли, IMP и разбор любого матча по ID.

### Docker

```bash
docker compose up -d --build
docker compose logs -f
```

---

## Команды

В командах `[в квадратных скобках]` — необязательное. Период: `день`, `неделя`, `месяц`, `год`, `всё`.

| Команда | Что делает |
|---|---|
| `/add ссылка_или_ID [имя] [MMR]` | добавить игрока (ссылка Dotabuff, OpenDota или Stratz, SteamID64 или account_id) |
| `/stats [сегодня\|неделя\|месяц]` | рейтинг, «Пульс пати» и награды |
| `/today` | статистика за сегодня |
| `/compare` | сравнение игроков (то же — `/table`) |
| `/together` | игры вместе и лучшая пара |
| `/player имя` | карточка игрока |
| `/heroes [имя или герой] [период]` | герои пати; с именем игрока — его герои и позиции; с названием героя — кто как на нём играет |
| `/roles [имя] [период]` | позиции 1–5 и винрейт на каждой (нужен Stratz) |
| `/match [id] [имя]` | разбор матча, по умолчанию последнего |
| `/records [период]` | рекорды отдельных игр |
| `/graph [период]` | график MMR |
| `/achievements [имя]` | достижения и антирекорды |
| `/steam имя` | Steam-профиль: аватарка, ник, ранг |
| `/list` · `/remove имя` · `/setmmr имя MMR` | список, удаление, поправка MMR |
| `/settings` | шаг MMR, час сводки, часовой пояс, оповещения |
| `/setstep число` · `/settime час` | шаг MMR и час сводки без меню |
| `/menu` · `/help` | меню с кнопками, справка |

`/add` берёт из ссылки только числовой `account_id`.

## Что бот делает сам

- Ежедневная сводка в заданный час: итоги за 24 часа, награды и рекорды; кнопки «Неделя» и «Месяц» переключают период.
- Оповещения о новых играх и достижениях (проверка раз в 4 минуты).
- Недельные итоги по понедельникам.
- Оповещения о смене ника или аватарки в Steam.
- Ежедневная копия БД в `<папка БД>/backups` (хранится `BACKUP_KEEP` копий, по умолчанию 7).

Оповещения и время сводки настраиваются в `/settings`. В групповых чатах у каждого чата свой рейтинг.

---

## Стек и структура

**Python 3.12 · aiogram 3 · SQLite · APScheduler · requests.** Данные: OpenDota API (ключ не нужен), Stratz GraphQL (по желанию).

```
mmrbot/
├── ids.py           разбор ссылок и ID → account_id
├── ranks.py         rank_tier → медаль
├── stats.py         чистые расчёты: победы, KDA, серии, оценка MMR
├── heroes.py        справочник героев
├── party.py         совместные игры, лучшая пара
├── achievements.py  достижения и антирекорды
├── awards.py        награды за период
├── records.py       рекорды отдельных игр
├── charts.py        график MMR (matplotlib → PNG)
├── commands.py      разбор аргументов команд
├── config.py        настройки из .env
├── opendota.py      клиент OpenDota (троттлинг, ретраи)
├── stratz.py        клиент Stratz (позиция, лейн, IMP)
├── storage.py       SQLite: чаты, игроки, кэш матчей
├── tracker.py       обновление игроков, сводки, награды
├── service.py       сборка отчётов для хендлеров и планировщика
├── formatting.py    тексты сообщений (Telegram HTML)
├── keyboards.py     inline-меню и кнопки
├── bot.py           хендлеры команд aiogram
├── scheduler.py     сводки, оповещения, бэкап
├── backup.py        копия SQLite
└── __main__.py      точка входа: python -m mmrbot
```

## Тесты

```bash
pytest
```

Логика изолирована от сети.

---

<p align="center"><sub>Данные предоставлены <a href="https://www.opendota.com/">OpenDota</a>. Проект не связан с Valve.</sub></p>
