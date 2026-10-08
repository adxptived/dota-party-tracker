# VPS: где и как работает бот

Секретов в этом файле нет. SSH-пароль и токены ботов лежат локально в `.vps/secrets.env`
(папка в `.gitignore`, в GitHub не попадает; формат — ниже).

## Сервер

| | |
|---|---|
| Хост | `moonbot.play2go.cloud`, IP `31.77.12.124`, SSH порт 22, пользователь `root` (по паролю) |
| ОС | Ubuntu, 2 ядра, 4 ГБ RAM, ~100 ГБ диска |
| Python | 3.12.15 (`/opt/dota-party-tracker/python/...`), системный — 3.14 (не использовать) |
| Docker | не установлен, бот запускается через systemd |

**На сервере живёт ещё таро-бот** (`shepot-tarot`, `shepot-autopost`, `shepot-support`, каталоги
`/opt/shepot-*`). Не трогать, его БД и env не удалять и не менять.

## Как устроен бот на сервере

- Сервис: `dota-party-tracker.service` (systemd), пользователь `dota-party`, `Restart=always`.
- Конфиг сервиса: `/etc/systemd/system/dota-party-tracker.service.d/override.conf` — тут путь к
  текущему релизу и venv. Именно он переключается при деплое и откате.
- Релизы: `/opt/dota-party-tracker/release-<дата>` (git clone из GitHub) и `venv-<дата>`.
  Старые релизы не удаляются — это откат. Раз в какое-то время чистите вручную.
- Env: `/etc/dota-party-tracker.env` (права 600, root). Ключи: `BOT_TOKEN`, `STRATZ_API_KEY`,
  `OPENDOTA_API_KEY`, а также обязательные `DB_PATH=/var/lib/dota-party-tracker/mmrbot.db` и
  `MPLCONFIGDIR` (`ProtectSystem=strict`, писать можно только в `/var/lib/dota-party-tracker`).
- Данные: `/var/lib/dota-party-tracker/` — боевая БД `mmrbot.db`, `backups/` (суточные копии, 7 шт.),
  кэши иконок и аватарок. Код при обновлении данные не затрагивает.
- Ручные бэкапы перед деплоями: `/opt/dota-party-tracker/predeploy-*.db`; прошлые env и override:
  `env-before-*.bak`, `override.conf.prev`.
- Репозиторий: `https://github.com/adxptived/dota-party-tracker`, ветка `main` (remote `fork`).

## Два бота

Один и тот же код умеет работать под любым из двух токенов, но на сервере в один момент активен **один**:
два процесса на одном токене конфликтуют (`TelegramConflictError`). Поэтому локальный бот
на токене, который сейчас стоит на сервере, держать запущенным нельзя.

| Бот | Токен в `.vps/secrets.env` | Примечание |
|---|---|---|
| `@keigroupsbot` (id 8997261910) | `BOT_TOKEN_KEI` | в основном чате у него есть право «Управление тегами»; он же в локальном `.env` |
| `@DOTA2chatTrack_bot` (id 8772458775) | `BOT_TOKEN_DOTA2CHATTRACK` | прежний боевой бот; на `2026-10-08` у него в основном чате `can_manage_tags=false` |

Текущий активный бот: смотрите `python scripts/vps.py status`. На момент написания — `@keigroupsbot`.

## Работа со скриптом `scripts/vps.py`

Нужен `pip install paramiko` и файл `.vps/secrets.env`:

```
VPS_HOST=31.77.12.124
VPS_PORT=22
VPS_USER=root
VPS_PASSWORD=...
BOT_TOKEN_KEI=...
BOT_TOKEN_DOTA2CHATTRACK=...
```

```
python scripts/vps.py status                       # сервис, активный бот, релиз, ресурсы, ошибки, таро-бот
python scripts/vps.py deploy                       # новый релиз из GitHub и перезапуск
python scripts/vps.py rollback                     # вернуть предыдущий релиз
python scripts/vps.py switch-bot kei               # или dota2chattrack: сменить токен и перезапустить
python scripts/vps.py logs 100                     # журнал
```

## Обновление бота (порядок)

1. Локально: `pytest`, `ruff check .`, коммит, `git push fork main`.
2. `python scripts/vps.py deploy`. Скрипт: клонирует репозиторий в новый `release-<время>`, ставит
   зависимости в новый venv, проверяет импорт, делает копию БД (`predeploy-<время>.db`), переключает
   `override.conf` и перезапускает сервис. Проверяет, что сервис `active` и нет `Conflict`.
3. Если что-то не так: `python scripts/vps.py rollback`. БД при этом откатывать не нужно,
   схема меняется только добавлением колонок (см. `CLAUDE.md`).
4. Новая настройка в `config.py` → добавить её в `/etc/dota-party-tracker.env` на сервере вручную
   (деплой env не трогает), потом перезапустить сервис.

## Ручные команды на сервере (по SSH)

```
systemctl status dota-party-tracker
journalctl -u dota-party-tracker -f -o cat
systemctl restart dota-party-tracker
cat /etc/systemd/system/dota-party-tracker.service.d/override.conf
```

## Теги участников (напоминание)

- Теги включаются в чате `/tags on`, синхронизируются раз в 30 минут.
- Боту в чате нужно право администратора «Управление тегами» (`can_manage_tags`).
- Тег ставится только привязанным игрокам (`/me ник`) и не ставится владельцу и админам чата.
- Один Telegram-аккаунт в чате привязывается только к одному игроку.
