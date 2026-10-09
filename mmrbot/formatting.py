"""Рендер сообщений бота — карточный дизайн, Telegram HTML.

Сообщения-борды (лидерборд, награды, совместка, герои, карточка игрока, список)
отправляются с parse_mode=HTML — имена экранируются через html.escape.
Обычные подтверждения/ошибки шлются обычным текстом (без разметки).
"""
from __future__ import annotations

import html
from typing import Optional

from mmrbot.heroes import hero_name
from mmrbot.ranks import rank_emoji, rank_label
from mmrbot.texts import NO_GAMES, NO_PLAYERS
from mmrbot.tracker import PlayerSummary

POSITIONS = {1: "🥇", 2: "🥈", 3: "🥉"}
LANE_NAMES = {1: "Лёгкая линия", 2: "Мид", 3: "Оффлейн", 4: "Лес"}


def _esc(text) -> str:
    return html.escape(str(text))


def _b(text) -> str:
    """Жирный с экранированием сырого текста."""
    return f"<b>{_esc(text)}</b>"


def _pos(index: int) -> str:
    return POSITIONS.get(index, f"{index}.")


def plural_games(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        word = "игра"
    elif 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        word = "игры"
    else:
        word = "игр"
    return f"{n} {word}"


def plural_heroes(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "герой"
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return "героя"
    return "героев"


def dotabuff_player_url(account_id: int) -> str:
    return f"https://www.dotabuff.com/players/{account_id}"


def dotabuff_match_url(match_id: int) -> str:
    return f"https://www.dotabuff.com/matches/{match_id}"


def format_delta(delta: int) -> str:
    if delta > 0:
        return f"+{delta}"
    if delta < 0:
        return str(delta)  # уже с минусом
    return "0"


def _trend(delta: int) -> str:
    if delta > 0:
        return f"  📈{format_delta(delta)}"
    if delta < 0:
        return f"  📉{format_delta(delta)}"
    return ""


def _today_delta(delta: int) -> str:
    if delta > 0:
        return f"📈{format_delta(delta)}"
    if delta < 0:
        return f"📉{format_delta(delta)}"
    return "±0"


def _mmr_str(current: Optional[int]) -> str:
    return f"≈ {current} MMR" if current is not None else "≈ ? MMR"


def fmt_local(ts: int, tz_name: str = "UTC", fmt: str = "%d.%m.%Y") -> str:
    """Unix-время → дата в часовом поясе чата (так же, как «сегодня»); для UTC добавляет пометку времени."""
    from datetime import datetime, timezone
    import pytz
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz, tz_name = pytz.utc, "UTC"
    text = datetime.fromtimestamp(ts or 0, tz=timezone.utc).astimezone(tz).strftime(fmt)
    return f"{text} UTC" if tz_name == "UTC" and "%H" in fmt else text


def _rank_with_emoji(s: PlayerSummary) -> str:
    prefix = f"{s.rank_emoji} " if s.rank_emoji else ""
    return f"{prefix}{s.rank}{' 🔒' if s.history_closed else ''}"


def _streak_str(s: PlayerSummary) -> str:
    if s.streak_len < 2:
        return ""
    return f"  🔥{s.streak_len} подряд" if s.streak_type == "W" else f"  💧{s.streak_len} подряд"


def _heroes_line(top_heroes: list[dict]) -> str:
    if not top_heroes:
        return "нет данных"
    return ", ".join(
        f"{_esc(hero_name(h['hero_id']))} ({plural_games(h['games'])}, {h['winrate'] * 100:.0f}%)" for h in top_heroes
    )


def _fmt_wr(games: int, wins: int) -> str:
    if not games:
        return "—"
    return f"{wins}–{games - wins} ({wins / games * 100:.0f}%)"


# --- лидерборд ----------------------------------------------------------

def _card_full(index: int, s: PlayerSummary) -> str:
    lines = [f"{_pos(index)} {_b(s.display_name)}"]
    lines.append(f"    {_rank_with_emoji(s)} · {_b(_mmr_str(s.current_mmr))}{_trend(s.mmr_delta)}")
    if s.games_total and s.anchor_games != s.games_total:  # стрелка и записи считаются за разные периоды — скажем
        lines.append(f"    <i>±MMR — за {plural_games(s.anchor_games)} с момента задания MMR</i>")
    if s.games_total == 0:
        lines.append(f"    {NO_GAMES}")
    else:
        perf = f" · перф {s.avg_perf * 100:.0f}" if s.avg_perf is not None else ""
        lines.append(
            f"    🎮 {plural_games(s.games_total)} · {s.wins_total}–{s.losses_total} "
            f"({s.winrate * 100:.0f}%) · KDA {s.kda_ratio:.2f}{perf}{_streak_str(s)}"
        )
        if s.games_today:
            lines.append(
                f"    📅 сегодня: {plural_games(s.games_today)}, "
                f"{_today_delta(s.delta_today)} ({s.wins_today}–{s.losses_today})"
            )
    return "\n".join(lines)


def _card_today(index: int, s: PlayerSummary) -> str:
    lines = [f"{_pos(index)} {_b(s.display_name)} · {_rank_with_emoji(s)}"]
    if s.games_today == 0:
        lines.append("    💤 сегодня игр не было")
    else:
        lines.append(
            f"    📅 сегодня: {plural_games(s.games_today)}, "
            f"{_today_delta(s.delta_today)} ({s.wins_today}–{s.losses_today})"
        )
    return "\n".join(lines)


def _age(seconds: int) -> str:
    minutes = max(1, seconds // 60)
    return f"{minutes} мин" if minutes < 90 else f"{minutes // 60} ч"


def stale_note(players: list, now: int, cooldown: int) -> str:
    """Предупреждение под отчётом, если кого-то не удалось обновить и показаны сохранённые данные.

    После обновления чата «свежий» игрок сверен не давнее кулдауна; всё, что заметно старше, —
    сбой запроса (OpenDota недоступен или исчерпан лимит). Пустая строка — все данные актуальны.
    """
    limit = cooldown + 120  # запас на длительность самого обновления
    stale = [p for p in players if p.updated_ts is None or now - p.updated_ts > limit]
    if not stale:
        return ""
    who = "" if len(stale) == len(players) else " (" + ", ".join(_esc(p.display_name) for p in stale) + ")"
    known = [p.updated_ts for p in stale if p.updated_ts is not None]
    when = f"обновлено {_age(now - min(known))} назад" if known else "ещё не загружены"
    return f"⚠️ <i>OpenDota не ответил — показаны сохранённые данные{who}: {when}.</i>"


def outage_note(
    status: Optional[dict], players: list, now: int, tz_name: str = "UTC", provider: str = "OpenDota"
) -> str:
    """Единая строка под отчётом и в подписи картинки: почему данные устарели и на какой момент они показаны.

    status — снимок ProviderHealth.status(); пока сервис жив (up) или предохранителя нет (None) — пустая строка.
    Время — в часовом поясе чата; другие сутки — с датой. Данные — по самому свежему обновлению игроков чата.
    """
    state = (status or {}).get("state")
    if state in (None, "up"):
        return ""

    def when(ts: int) -> str:
        same_day = fmt_local(ts, tz_name, "%Y-%m-%d") == fmt_local(now, tz_name, "%Y-%m-%d")
        return fmt_local(ts, tz_name, "%H:%M" if same_day else "%d.%m %H:%M")

    since = status.get("since")
    since_part = f" с {when(since)}" if since else ""
    loaded = [p.updated_ts for p in players if p.updated_ts is not None]
    data = f"показаны данные на {when(max(loaded))}" if loaded else "данные ещё не загружены"
    what = "ограничил запросы" if state == "limited" else "недоступен"
    return f"⚠️ <i>{provider} {what}{since_part} — {data}.</i>"


def render_leaderboard(summaries: list[PlayerSummary], today_only: bool = False) -> str:
    if not summaries:
        return NO_PLAYERS

    if today_only:
        header = "📅 <b>Статистика за сегодня</b>"
        blocks = [_card_today(i, s) for i, s in enumerate(summaries, start=1)]
        return header + "\n\n" + "\n\n".join(blocks)

    header = "🏆 <b>Рейтинг</b>\n<i>игры — с начала отслеживания, ±MMR — оценка от стартового MMR</i>"
    blocks = [_card_full(i, s) for i, s in enumerate(summaries, start=1)]
    return header + "\n\n" + "\n\n".join(blocks)


def render_period_leaderboard(rows: list[dict], period: str) -> str:
    """Лидерборд за неделю/месяц: победы–поражения, винрейт, оценка MMR-дельты."""
    if not rows:
        return render_leaderboard([])
    label = {"week": "за неделю", "month": "за месяц"}.get(period, "за период")
    blocks = []
    for i, r in enumerate(rows, start=1):
        head = f"{_pos(i)} {_b(r['name'])}"
        if r["games"] == 0:
            blocks.append(f"{head}\n    💤 игр не было")
            continue
        blocks.append(
            f"{head} · {_today_delta(r['delta'])}\n"
            f"    🎮 {plural_games(r['games'])} · {r['wins']}–{r['losses']} "
            f"({r['winrate'] * 100:.0f}%) · KDA {r['kda']:.2f}"
        )
    return f"📅 <b>Статистика {label}</b>\n\n" + "\n\n".join(blocks)


# --- награды ------------------------------------------------------------

def render_awards(awards: list[dict], label: str = "за неделю") -> str:
    """Отличия участников за период (label — «за сутки»/«за неделю»); пусто, если сравнивать нечего."""
    if not awards:
        return ""
    lines = [f"🏅 <b>Награды {label}</b>"]
    for award in awards:
        lines.append(f"{award['emoji']} {_esc(award['title'])} — {_b(award['player'])} ({_esc(award['detail'])})")
    return "\n".join(lines)


PULSE_RECORDS = ("gpm", "kills", "imp")  # какие рекорды недели выносим в «Стату пати»


def _form_dots(form: list) -> str:
    return "".join("🟢" if won else "🔴" for won in form)


def render_party_pulse(
    summaries: list[PlayerSummary], week_rows: list[dict], week_records: dict,
    day_rows: Optional[list[dict]] = None,
) -> str:
    """«Стата пати» под рейтингом: сегодня, неделя, форма игроков, рекорды недели (работает и для одного игрока)."""
    lines = ["📊 <b>Стата пати</b>"]

    if day_rows is not None:  # ежедневная сводка уходит утром: «сегодня» почти пусто — показываем последние сутки
        played_day = [r for r in day_rows if r["games"] > 0]
        d_games = sum(r["games"] for r in played_day)
        if d_games:
            d_wins = sum(r["wins"] for r in played_day)
            d_delta = sum(r["delta"] for r in played_day)
            lines.append(f"🌅 За сутки: {plural_games(d_games)} · {_fmt_wr(d_games, d_wins)} · {_today_delta(d_delta)}")
        else:
            lines.append("🌅 За сутки: игр не было")
    t_games = sum(s.games_today for s in summaries)
    if day_rows is not None:
        pass  # строка «За сутки» выше заменяет «Сегодня»
    elif t_games:
        t_wins = sum(s.wins_today for s in summaries)
        t_delta = sum(s.delta_today for s in summaries)
        lines.append(f"📅 Сегодня: {plural_games(t_games)} · {_fmt_wr(t_games, t_wins)} · {_today_delta(t_delta)}")
    else:
        lines.append("📅 Сегодня: игр пока не было")

    played = [r for r in week_rows if r["games"] > 0]
    if played:
        w_games = sum(r["games"] for r in played)
        w_wins = sum(r["wins"] for r in played)
        w_delta = sum(r["delta"] for r in played)
        lines.append(f"🗓️ За неделю: {plural_games(w_games)} · {_fmt_wr(w_games, w_wins)} · {_today_delta(w_delta)}")
        if len(played) >= 2:
            best = max(played, key=lambda r: r["delta"])
            if best["delta"] > 0:
                lines.append(f"🚀 Лидер недели: {_b(best['name'])} {_today_delta(best['delta'])} ({best['wins']}–{best['losses']})")
    else:
        lines.append("🗓️ За неделю: игр не было")

    form = [s for s in summaries if s.recent_form]
    if form:
        lines.append("")
        lines.append("<b>Форма</b> <i>(последние игры, новые справа)</i>")
        for s in form:
            lines.append(f"{_b(s.display_name)}  {_form_dots(s.recent_form)}")

    picked = [r for r in week_records.get("records", []) if r["key"] in PULSE_RECORDS]
    if picked:
        lines.append("")
        lines.append("🌟 <b>Рекорды недели</b>")
        for r in picked:
            match = r["match"]
            lines.append(
                f"{r['emoji']} {_esc(r['text'])} — {_b(r['player'])} · {_esc(hero_name(match.get('hero_id')))} · "
                f'<a href="{dotabuff_match_url(match["match_id"])}">матч</a>'
            )
        lines.append("<i>Все рекорды за день/месяц/год — /records</i>")
    return "\n".join(lines)


# --- совместная игра ----------------------------------------------------

def render_together(result: dict) -> str:
    summary = result.get("summary", {})
    games = summary.get("games", 0)
    if games == 0:
        return (
            "🤝 <b>Совместные игры</b>\n\n"
            "😴 Совместные ранкед-игры не обнаружены (возможно, данные ещё загружаются).\n"
            "После первой совместной игры будут доступны общий винрейт и лучшая пара."
        )
    lines = [
        "🤝 <b>Совместные игры</b>",
        "",
        f"🎮 Сыграно вместе: {_b(plural_games(games))} · {_fmt_wr(games, summary.get('wins', 0))}",
    ]
    duo = result.get("duo")
    if duo:
        n1, n2 = duo["pair"]
        lines.append(
            f"💞 Лучшая пара: <b>{_esc(n1)} + {_esc(n2)}</b> — "
            f"{plural_games(duo['games'])}, {_fmt_wr(duo['games'], duo['wins'])}"
        )
    return "\n".join(lines)


# --- герои --------------------------------------------------------------

def render_heroes(summaries: list[PlayerSummary]) -> str:
    if not summaries:
        return NO_PLAYERS
    lines = ["🦸 <b>Любимые герои</b>"]
    for s in summaries:
        lines.append(f"• {_b(s.display_name)}: {_heroes_line(s.top_heroes)}")
    return "\n".join(lines)


# --- карточка игрока ----------------------------------------------------

SKILL_GROUPS = [
    ("Фарм", ["gold_per_min", "last_hits_per_min", "xp_per_min"]),
    ("Урон", ["hero_damage_per_min", "tower_damage"]),
    ("Участие в боях", ["kills_per_min", "assists_per_min"]),
    ("Поддержка", ["hero_healing_per_min"]),
]


def _bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct * width)))
    return "▰" * filled + "▱" * (width - filled)


def _skill_block(skill: dict) -> Optional[str]:
    """Объективный профиль скилла: перцентиль по категориям (50% = средний игрок)."""
    if not skill:
        return None
    lines = ["🧠 <b>Профиль навыков</b> <i>(мировой перцентиль; 50% — средний уровень)</i>"]
    for label, metrics in SKILL_GROUPS:
        pcts = [skill[m] for m in metrics if m in skill]
        if not pcts:
            continue
        avg = sum(pcts) / len(pcts)
        lines.append(f"   {label}  {_bar(avg)} {avg * 100:.0f}%")
    return "\n".join(lines) if len(lines) > 1 else None


def _k(value) -> str:
    """Компактно: 13656 → 13.7k, 428 → 428."""
    if value is None:
        return "—"
    return f"{value / 1000:.1f}k" if value >= 1000 else f"{value:.0f}"


def _form_icons(form: list) -> str:
    return _form_dots(form)


def _wr_ratio(pair: tuple) -> Optional[float]:
    games, wins = pair
    return wins / games if games else None


LEAD_NAMES = {"perf": "перф", "winrate": "винрейт", "kda": "KDA", "gpm": "GPM"}


def standing_line(comparison: dict, name: str) -> Optional[str]:
    """Строка «место в чате» для игрока (None, если сравнивать не с кем)."""
    if comparison["size"] < 2:
        return None
    player = comparison["players"].get(name)
    if not player:
        return None
    ranks = player["ranks"]
    parts = [_b(f"сила #{player['power_rank']}")]
    for key, label in (("perf", "перф"), ("winrate", "винрейт"), ("kda", "KDA")):
        if key in ranks:
            parts.append(f"{label} #{ranks[key]}")
    line = f"📍 Позиция в чате (из {comparison['size']}): " + " · ".join(parts)
    if player["leads"]:
        line += "\n👑 Лидирует по показателям: " + ", ".join(LEAD_NAMES[m] for m in player["leads"])
    return line


def _place(ranks: dict, key: str) -> str:
    """« (#2)» — место по показателю; пусто, если он посчитан по слишком малому числу игр и в ранжирование не вошёл."""
    return f" (#{ranks[key]})" if key in ranks else ""


def render_compare_table(comparison: dict, summaries: list[PlayerSummary]) -> str:
    """Сравнительная таблица: игроки по «силе в чате» + ранги по метрикам."""
    order = sorted(summaries, key=lambda s: comparison["players"][s.display_name]["power_rank"])
    lines = [f"⚖️ <b>Сравнение игроков</b> <i>(участников: {comparison['size']})</i>", ""]
    for s in order:
        player = comparison["players"][s.display_name]
        ranks = player["ranks"]
        power = player["power"]
        power_str = f"{power * 100:.0f}" if power is not None else "—"
        lines.append(f"{_pos(player['power_rank'])} {_b(s.display_name)} — индекс {_b(power_str)}")
        parts = []
        if s.avg_perf is not None:
            parts.append(f"перф {s.avg_perf * 100:.0f}{_place(ranks, 'perf')}")
        if s.games_total:
            parts.append(f"винрейт {s.winrate * 100:.0f}%{_place(ranks, 'winrate')}")
            parts.append(f"KDA {s.kda_ratio:.1f}{_place(ranks, 'kda')}")
        if s.avg_gpm_window is not None:
            parts.append(f"GPM {s.avg_gpm_window:.0f}{_place(ranks, 'gpm')}")
        if parts:
            lines.append("    " + " · ".join(parts))
    return "\n".join(lines)


def render_player_card(s: PlayerSummary, standing: Optional[str] = None) -> str:
    """Карточка игрока — ТОЛЬКО окно отслеживания (последние игры), без карьерных срезов."""
    header = f"{_b(s.display_name)} · {_rank_with_emoji(s)}{_streak_str(s)}"
    if s.steam_name:
        header += f"\n🎮 Steam: {_b(s.steam_name)}"
    if s.games_total == 0:
        return header + f"\n{NO_GAMES}"

    lines = [header, f"<i>🔎 Вся ранкед-история с момента добавления: {plural_games(s.games_total)}</i>", ""]

    # Заголовочная строка: MMR + честный перф рядом.
    perf = f"    перф {_b(f'{s.avg_perf * 100:.0f}/100')}" if s.avg_perf is not None else ""
    lines.append(f"{_b(_mmr_str(s.current_mmr))}{_trend(s.mmr_delta)}{perf}")
    if s.mmr_drift:
        lines.append(f"<i>⚠️ Оценка MMR расходится с медалью {_esc(s.rank)} — обновите стартовый: /setmmr</i>")
    lines.append(f"{s.wins_total}–{s.losses_total} ({s.winrate * 100:.0f}%)   последние игры: {_form_icons(s.recent_form)}")

    # Бой + экономика (всё за окно).
    lines.append(f"KDA {s.kda_ratio:.2f} ({s.avg_kills:.0f}/{s.avg_deaths:.0f}/{s.avg_assists:.0f})")
    econ = []
    if s.avg_gpm_window is not None:
        econ.append(f"{s.avg_gpm_window:.0f} gpm")
    if s.avg_net_worth_window is not None:
        econ.append(f"{_k(s.avg_net_worth_window)} нетворт")
    if s.avg_hero_damage_window is not None:
        econ.append(f"{_k(s.avg_hero_damage_window)} урон")
    if econ:
        part = f" (по {s.detail_games} из {s.games_total})" if 0 < s.detail_games < s.games_total else ""
        lines.append("💰 Экономика: " + " · ".join(econ) + part)

    # Объективный скилл (перцентиль в мире) + стиль/роль.
    if s.role_style:
        lines.append(f"🎭 Игровая роль: {s.role_style}")
    skill_block = _skill_block(s.skill)
    if skill_block:
        lines.append("")
        lines.append(skill_block)

    lines.append("")

    # Разрезы + подсказки.
    solo_wr, party_wr = _wr_ratio(s.solo), _wr_ratio(s.party)
    note = ""
    if solo_wr is not None and party_wr is not None and s.party[0] >= 2 and party_wr < solo_wr - 0.2:
        note = "   (в группе результат ниже)"
    lines.append(f"👤 Соло: {_fmt_wr(*s.solo)} · в группе: {_fmt_wr(*s.party)}{note}")
    if s.party_unknown[0]:
        lines.append(f"      <i>размер пати неизвестен: {plural_games(s.party_unknown[0])} — в разбивку не вошли</i>")

    if s.best_hour and s.worst_hour:
        bh, bwr = s.best_hour
        wh, wwr = s.worst_hour
        lines.append(f"⏰ Лучший час: {bh:02d}:00 ({bwr * 100:.0f}%) · худший: {wh:02d}:00 ({wwr * 100:.0f}%)")
    if s.avg_duration_min:
        lines.append(f"⏱️ Средняя длительность: {s.avg_duration_min:.0f} мин (максимум {s.max_duration_min:.0f})")
    if s.lobby_rank:
        lines.append(f"🎚️ Средний уровень лобби: {rank_label(s.lobby_rank)}")
    win, loss = s.wins_losses.get("win"), s.wins_losses.get("loss")
    if win and loss:
        lines.append(
            f"⚔️ KDA в победах: {win['avg_kda']:.1f} (смертей {win['avg_deaths']:.0f}) · "
            f"в поражениях: {loss['avg_kda']:.1f} (смертей {loss['avg_deaths']:.0f})"
        )
    if s.last_game:
        lg = s.last_game
        lines.append(
            f"🕹️ Последняя игра: {_esc(hero_name(lg['hero_id']))} {lg['kills']}/{lg['deaths']}/{lg['assists']} · "
            f"{'🏆 победа' if lg['won'] else '💀 поражение'}"
        )
    if s.longest_win_streak >= 2:
        lines.append(f"🔥 Наибольшая серия побед: {s.longest_win_streak}")
    pool = f" (всего {s.hero_pool})" if s.hero_pool else ""
    lines.append(f"🦸 Герои{pool}: {_heroes_line(s.top_heroes)}")

    if standing:
        lines.append("")
        lines.append(standing)

    if s.history_closed:
        lines.append("<i>🔒 История матчей закрыта у OpenDota — игры могли не загрузиться, цифры неполные.</i>")
    lines.append("")
    lines.append(
        f'🔗 <a href="{dotabuff_player_url(s.account_id)}">Dotabuff</a> · '
        f'<a href="https://www.opendota.com/players/{s.account_id}">OpenDota</a>'
    )
    if s.avg_perf is not None:
        pct = f"{s.avg_perf * 100:.0f}"
        part = f" Посчитан по {s.enriched_games} из {s.games_total} игр." if s.enriched_games < s.games_total else ""
        lines.append(f"<i>ℹ️ Перф {pct} — лучше, чем у {pct}% игроков на том же герое.{part}</i>")
    else:
        lines.append("<i>ℹ️ Перф — сравнение с игроками на том же герое.</i>")
    return "\n".join(lines)


# --- список игроков -----------------------------------------------------

def render_player_list(summaries: list[PlayerSummary]) -> str:
    """Список игроков: ранг, текущий MMR (оценка) со стартом и дельтой, игры, серия, id аккаунта."""
    if not summaries:
        return NO_PLAYERS
    blocks = []
    for i, s in enumerate(summaries, start=1):
        if s.current_mmr is not None:
            mmr = f"🎯 {_b(_mmr_str(s.current_mmr))} (старт {s.anchor_mmr}{_trend(s.mmr_delta)})"
            if s.mmr_drift:
                mmr += " ⚠️ расходится с медалью — /setmmr"
        else:
            mmr = "🎯 MMR не указан (задать: /setmmr)"
        if s.games_total:
            games = (
                f"🎮 {plural_games(s.games_total)} · {s.wins_total}–{s.losses_total} "
                f"({s.winrate * 100:.0f}%){_streak_str(s)}"
            )
        else:
            games = NO_GAMES
        blocks.append(
            f"{_pos(i)} {_b(s.display_name)} · {_rank_with_emoji(s)}\n"
            f"    {mmr}\n    {games}\n    🆔 id {s.account_id}"
        )
    return f"👥 <b>Отслеживаемые игроки</b> · {len(summaries)}\n\n" + "\n\n".join(blocks)


# --- Steam-профиль ------------------------------------------------------

def country_flag(code) -> str:
    """ISO-код страны → эмодзи-флаг (пусто, если код некорректный)."""
    if not isinstance(code, str) or len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


def render_steam_profile(display_name: str, account_id: int, profile: dict, rank: str) -> str:
    """Подпись к аватарке: текущий ник в Steam, ник в боте, ссылка, id, ранг, страна, Dota Plus."""
    steam_name = profile.get("personaname")
    flag = country_flag(profile.get("loccountrycode"))
    lines = [f"🎮 <b>{_esc(steam_name or display_name)}</b>{(' ' + flag) if flag else ''}"]
    if steam_name and steam_name != display_name:
        lines.append(f"🏷️ В боте: {_b(display_name)}")
    lines.append(f"🏅 {_esc(rank)}")
    if profile.get("plus"):
        lines.append("💎 Dota Plus")
    if profile.get("profileurl"):
        lines.append(f"🔗 {_esc(profile['profileurl'])}")
    ids = f"🆔 account {account_id}"
    if profile.get("steamid"):
        ids += f" · SteamID64 {_esc(profile['steamid'])}"
    lines.append(ids)
    # last_login в OpenDota — вход на сайт OpenDota, а не в Dota; выводить его как «последний вход» нельзя.
    return "\n".join(lines)


def render_steam_change(player, changes: dict) -> str:
    """Оповещение о смене ника и/или аватарки Steam."""
    lines = []
    if "name" in changes:
        old, new = changes["name"]
        lines.append(f"🔔 {_b(player.display_name)} сменил ник в Steam: {_esc(old)} ➜ {_b(new)}")
    if changes.get("avatar"):
        lines.append(f"🖼️ {_b(player.display_name)} сменил аватарку в Steam")
    return "\n".join(lines)


# --- оповещения, достижения, недельная сводка --------------------------

def _thousands(value) -> str:
    """31250 → «31.2k»; меньше тысячи — как есть."""
    value = int(value)
    return f"{value // 100 / 10:.1f}k" if value >= 1000 else str(value)


def render_start_alert(event: dict) -> str:
    """Оповещение «зашёл в Dota 2»: кто и сколько пати сейчас в игре (Steam не отдаёт героя и момент старта матча)."""
    names = ", ".join(_b(n) for n in event["names"])
    verb = "зашли" if len(event["names"]) > 1 else "зашёл"
    line = f"🟢 {names} {verb} в Dota 2"
    if event.get("in_game", 0) >= 2:
        line += f" · в игре {event['in_game']}/{event['total']}"
    return line


def _mvp_name(rows: list) -> Optional[str]:
    """Лучший в матче среди игроков пати (нужно ≥2): по IMP, если он есть у всех, иначе по (K+A)/D."""
    if len(rows) < 2:
        return None
    if all(r.get("imp") is not None for r in rows):
        key = lambda r: r["imp"]  # noqa: E731
    else:
        key = lambda r: (r["kills"] + r["assists"]) / max(r["deaths"], 1)  # noqa: E731
    return max(rows, key=key)["name"]


def render_game_alert(event: dict) -> str:
    """Оповещение о конце матча: результат пати, длительность и по строке на каждого отслеживаемого игрока."""
    rows = event["rows"]
    wins = sum(1 for r in rows if r["won"])
    result = "Победа" if wins == len(rows) else "Поражение" if wins == 0 else "Разные стороны"
    icon = "🏆" if wins == len(rows) else "💀" if wins == 0 else "⚔️"
    duration = f" · {event['duration'] // 60} мин" if event.get("duration") else ""
    match_id = event["match_id"]
    mvp = _mvp_name(rows)
    lines = [
        f"🏁 <b>Матч завершён</b> · {icon} {result}{duration} · "
        f'<a href="{dotabuff_match_url(match_id)}">Dotabuff</a> · '
        f'<a href="https://www.opendota.com/matches/{match_id}">OpenDota</a>'
    ]
    if event.get("average_rank"):
        lines.append(f"🎚 Лобби: {rank_emoji(event['average_rank'])} {_esc(rank_label(event['average_rank']))}".replace("  ", " "))
    for r in rows:
        delta = r["step"] if r["won"] else -r["step"]
        line = (
            f"{'🏆' if r['won'] else '💀'} {_b(r['name'])}{' ⭐' if r['name'] == mvp else ''} — {_esc(hero_name(r['hero_id']))} "
            f"{r['kills']}/{r['deaths']}/{r['assists']} · {_today_delta(delta)}"
        )
        if r.get("current_mmr") is not None:
            line += f" ➜ ≈{r['current_mmr']} MMR"
        if r.get("streak_len", 0) >= 3:
            line += f"  {'🔥' if r['streak_type'] == 'W' else '💧'}{r['streak_len']} подряд"
        extra = []
        if r.get("position"):
            extra.append(f"Pos {r['position']}")
        if r.get("imp") is not None:
            extra.append(f"IMP {r['imp']:+d}")
        if r.get("gpm"):
            extra.append(f"{round(r['gpm'])} GPM")
        if r.get("hero_damage"):
            extra.append(f"{_thousands(r['hero_damage'])} урона")
        if extra:
            line += f"\n      <i>{' · '.join(extra)}</i>"
        if (r.get("leaver_status") or 0) >= 2:
            line += "\n      ⚠️ <i>покинул игру — такая игра считается иначе</i>"
        lines.append(line)
    shared = event.get("shared")
    if shared and shared.get("games"):
        lines.append(f"🤝 Сегодня вместе: {plural_games(shared['games'])} · {shared['wins']}–{shared['losses']}")
    return "\n".join(lines)


def render_contest(period_label: str, standings: list[dict], points: list[dict]) -> str:
    """Соревнование чата текстом: общий зачёт и топ-3 по каждой номинации (антирекорды — отдельным блоком)."""
    if not standings:
        return f"🏅 <b>Соревнование {period_label}</b>\n\n💤 Пока не с кем соревноваться: нужны двое игроков с играми за период."
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"🏅 <b>Соревнование {period_label}</b>", "", "<b>Общий зачёт</b> · 3/2/1 очко за места"]
    rank = 1
    for i, row in enumerate(points):
        if i and (row["points"], row["golds"]) != (points[i - 1]["points"], points[i - 1]["golds"]):
            rank = i + 1
        lines.append(f"{medals.get(rank, '▫️')} {_b(row['player'])} — {row['points']} очк.")
    for anti, title in ((False, "Номинации"), (True, "Антирекорды")):
        block = [s for s in standings if s["anti"] == anti]
        if not block:
            continue
        lines += ["", f"<b>{title}</b>"]
        for s in block:
            lines.append(f"{s['emoji']} {_esc(s['title'])}")
            for e in s["entries"]:
                lines.append(f"    {medals.get(e['place'], '▫️')} {_b(e['player'])} — {_esc(e['text'])}")
    return "\n".join(lines)


def render_leader_change(period_label: str, changes: list[dict]) -> str:
    """Объявление: кто кого обошёл в номинациях соревнования."""
    lines = [f"🔄 <b>Смена лидера {period_label}</b>"]
    for c in changes:
        lines.append(f"{c['emoji']} {_esc(c['title'])}: {_b(c['new'])} обошёл {_b(c['old'])} ({_esc(c['text'])})")
    return chr(10).join(lines)


_WEEKLY_DUPLICATES = {"climb", "drop", "games", "win_streak"}  # эти итоги недели уже есть в шапке сводки


def render_weekly(report: dict) -> str:
    rows = [r for r in report["rows"] if r["games"] > 0]
    if not rows:
        return "📅 <b>Итоги недели</b>\n\n💤 За неделю ранкед-игр не было."
    games = sum(r["games"] for r in rows)
    wins = sum(r["wins"] for r in rows)
    lines = ["📅 <b>Итоги недели</b>", "", f"🎮 Всего: {plural_games(games)} · {_fmt_wr(games, wins)}"]
    champion = report.get("champion")
    if champion:
        lines.append(f"🏆 Чемпион недели: {_b(champion['player'])} — {champion['points']} очк. (/achievements)")
    best = max(rows, key=lambda r: r["delta"])
    worst = min(rows, key=lambda r: r["delta"])
    if best["delta"] > 0:
        lines.append(f"🚀 Больше всех поднялся: {_b(best['name'])} {_today_delta(best['delta'])} ({best['wins']}–{best['losses']})")
    if worst["delta"] < 0 and worst is not best:
        lines.append(f"📉 Больше всех просел: {_b(worst['name'])} {_today_delta(worst['delta'])} ({worst['wins']}–{worst['losses']})")
    busiest = max(rows, key=lambda r: r["games"])
    lines.append(f"🕹️ Больше всех играл: {_b(busiest['name'])} — {plural_games(busiest['games'])}")
    hero = report.get("hero")
    if hero:
        lines.append(
            f"🦸 Герой недели: {_b(hero_name(hero['hero_id']))} — {plural_games(hero['games'])} · "
            f"{hero['wins'] / hero['games'] * 100:.0f}%"
        )
    if report.get("streak"):
        name, length = report["streak"]
        lines.append(f"🔥 Лучшая серия: {_b(name)} — {length} побед подряд")
    shared = report.get("shared") or {}
    if shared.get("games"):
        lines.append(f"🤝 Вместе: {plural_games(shared['games'])} · {shared['wins']}–{shared['losses']}")
    lines.append("")
    for i, r in enumerate(sorted(rows, key=lambda r: r["delta"], reverse=True), start=1):
        lines.append(
            f"{_pos(i)} {_b(r['name'])} · {_today_delta(r['delta'])} · "
            f"{r['wins']}–{r['losses']} ({r['winrate'] * 100:.0f}%)"
        )
    awards = [a for a in report.get("awards") or [] if a["key"] not in _WEEKLY_DUPLICATES]
    if awards:  # лучшие показатели недели (подъём/просадка/активность уже выше в сводке)
        lines.append("")
        lines.append("🏅 <b>Лучшие показатели недели</b>")
        for award in awards:
            lines.append(f"{award['emoji']} {_esc(award['title'])} — {_b(award['player'])} ({_esc(award['detail'])})")
    return "\n".join(lines)


# --- ежедневная сводка: скользящие 24 часа до отправки ----------------------------------------------

_MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
DAILY_RECORD_ORDER = ("kills", "kda", "gpm", "hero_damage", "imp", "assists", "last_hits", "net_worth",
                      "tower_damage", "hero_healing", "duration")


def local_time(ts: int, tz_name: str):
    from datetime import datetime, timezone
    import pytz
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.utc
    return datetime.fromtimestamp(ts or 0, tz=timezone.utc).astimezone(tz)


def fmt_stamp(ts: int, tz_name: str = "UTC") -> str:
    """«9 окт 12:26» — момент в часовом поясе чата."""
    local = local_time(ts, tz_name)
    return f"{local.day} {_MONTHS[local.month - 1]} {local:%H:%M}"


def fmt_clock(ts: int, tz_name: str, ref: int) -> str:
    """«14:05» в часовом поясе чата; если это не тот день, что у `ref`, — с датой («8 окт 23:10»)."""
    local = local_time(ts, tz_name)
    if local.date() != local_time(ref, tz_name).date():
        return fmt_stamp(ts, tz_name)
    return f"{local:%H:%M}"


def fmt_window(report: dict) -> str:
    """Окно сводки суток: «8 окт 12:00 → 9 окт 12:00»."""
    tz = report.get("tz", "UTC")
    return f"{fmt_stamp(report['since'], tz)} → {fmt_stamp(report['until'], tz)}"


def fmt_minutes(minutes: float) -> str:
    """«3 ч 20 мин», «2 ч», «45 мин»."""
    hours, rest = divmod(round(minutes), 60)
    if not hours:
        return f"{rest} мин"
    return f"{hours} ч {rest} мин" if rest else f"{hours} ч"


def plural_wins(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        word = "победа"
    elif 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        word = "победы"
    else:
        word = "побед"
    return f"{n} {word}"


def daily_record_picks(records: list[dict], limit: int = 6) -> list[dict]:
    """Рекорды суток для сводки: сначала самые наглядные (убийства, KDA, GPM…), без антирекордов, не больше limit."""
    by_key = {r["key"]: r for r in records if not r.get("anti")}
    return [by_key[key] for key in DAILY_RECORD_ORDER if key in by_key][:limit]


def best_game_stats(match: dict) -> list[tuple[str, str]]:
    """Показатели лучшей игры суток, которые известны: [(подпись, значение)] — нетворс, GPM/XPM, урон, IMP, длительность."""
    out: list[tuple[str, str]] = []
    if match.get("net_worth"):
        out.append(("Нетворс", _k(match["net_worth"])))
    gpm, xpm = match.get("gpm"), match.get("xpm")
    if gpm is not None:
        out.append(("GPM / XPM", f"{gpm:.0f} / {xpm:.0f}" if xpm is not None else f"{gpm:.0f}"))
    if match.get("hero_damage"):
        out.append(("Урон по героям", _k(match["hero_damage"])))
    if match.get("tower_damage"):
        out.append(("Урон по зданиям", _k(match["tower_damage"])))
    if match.get("hero_healing"):
        out.append(("Лечение", _k(match["hero_healing"])))
    if match.get("imp") is not None:
        out.append(("IMP", f"{match['imp']:+.0f}"))
    if match.get("duration"):
        out.append(("Длительность", f"{match['duration'] // 60}:{match['duration'] % 60:02d}"))
    return out


def item_title(item_id) -> str:
    """id предмета → читаемое имя из внутреннего («black_king_bar» → «Black King Bar»); неизвестный — пустая строка."""
    from mmrbot.items import item_slug
    slug = item_slug(item_id) if isinstance(item_id, int) and not isinstance(item_id, bool) else None
    return slug.replace("_", " ").title() if slug else ""


def best_game_build_line(build: Optional[dict]) -> str:
    """Билд одной строкой: предметы со временем покупки, нейтралка, шард и скипетр. Пусто — билд неизвестен."""
    if not build:
        return ""
    times = build.get("item_times") if isinstance(build.get("item_times"), list) else []
    parts = []
    for i, item_id in enumerate(build.get("items") or []):
        name = item_title(item_id)
        if name:
            when = times[i] if i < len(times) and isinstance(times[i], (int, float)) and not isinstance(times[i], bool) else None
            parts.append(f"{name} {int(when) // 60}:{int(when) % 60:02d}" if when is not None else name)
    line = " → ".join(parts)
    neutral = item_title(build.get("neutral_item"))
    extra = [f"нейтралка: {neutral}"] if neutral else []
    for key, label in (("shard", "Шард"), ("scepter", "Скипетр")):
        if build.get(key):
            when = build.get(f"{key}_time")
            extra.append(f"{label} {int(when) // 60}:{int(when) % 60:02d}" if isinstance(when, (int, float)) and not isinstance(when, bool) else label)
    return " · ".join(x for x in [line] + extra if x)


def render_daily_best_game(best: Optional[dict]) -> str:
    """Блок «Лучшая игра суток»: игрок, герой, исход, K/D/A, KDA, показатели и билд (если известен)."""
    if not best:
        return ""
    match = best["match"]
    outcome = "победа" if best.get("won") else "поражение"
    lines = [
        "🎯 <b>Лучшая игра суток</b>",
        f"{_b(best['player'])} · {_esc(hero_name(match.get('hero_id')))} · {outcome} · "
        f'<a href="{dotabuff_match_url(match["match_id"])}">матч</a>',
        f"⚔️ {best['kills']}/{best['deaths']}/{best['assists']} · KDA {best['kda']:.2f}",
    ]
    stats_line = " · ".join(f"{label} {value}" for label, value in best_game_stats(match))
    if stats_line:
        lines.append("📊 " + _esc(stats_line))
    build = best_game_build_line(best.get("build"))
    if build:
        lines.append("🛒 " + _esc(build))
    return "\n".join(lines)


def render_daily(report: dict, info: Optional[dict] = None) -> str:
    """Ежедневная сводка — итоги последних 24 часов до отправки: игроки, лидеры, герой, серия, рекорды, награды.

    info — {ник: {"mmr", "rank_text"}}: текущая оценка MMR и ранг игроков (необязательно).
    """
    info = info or {}
    tz = report.get("tz", "UTC")
    head = ["📰 <b>Ежедневная сводка</b>", f"<i>за последние 24 часа · {fmt_window(report)}</i>"]
    rows = [r for r in report["rows"] if r["games"] > 0]
    if not rows:
        return "\n".join(head + ["", "💤 За последние 24 часа ранкед-игр не было."])
    totals = report["totals"]
    lines = head + ["", f"🎮 Всего: {plural_games(totals['games'])} · {_fmt_wr(totals['games'], totals['wins'])} · "
                        f"{_today_delta(totals['delta'])}"]
    if len(rows) >= 2:  # «лидер» и «больше всех» — сравнение: с одним игроком смысла нет
        best = max(rows, key=lambda r: (r["delta"], r["wins"]))
        if best["delta"] > 0:
            lines.append(f"🚀 Лидер суток: {_b(best['name'])} {_today_delta(best['delta'])} ({best['wins']}–{best['losses']})")
        worst = min(rows, key=lambda r: (r["delta"], -r["wins"]))
        if worst["delta"] < 0 and worst is not best:
            lines.append(f"📉 Больше всех просел: {_b(worst['name'])} {_today_delta(worst['delta'])} ({worst['wins']}–{worst['losses']})")
        busiest = max(rows, key=lambda r: r["games"])
        lines.append(f"🕹️ Больше всех играл: {_b(busiest['name'])} — {plural_games(busiest['games'])}")
    if totals.get("minutes"):
        avg = f" · в среднем {fmt_minutes(totals['avg_minutes'])} за игру" if totals.get("avg_minutes") else ""
        lines.append(f"⏱️ В игре: {fmt_minutes(totals['minutes'])} суммарно{avg}")
    if report.get("first_start") is not None:
        lines.append(f"🕐 Играли с {fmt_clock(report['first_start'], tz, report['until'])} "
                     f"до {fmt_clock(report['last_end'], tz, report['until'])}")
    hero = report.get("hero")
    if hero:
        lines.append(f"🦸 Герой суток: {_b(hero_name(hero['hero_id']))} — {plural_games(hero['games'])} · "
                     f"{hero['wins'] / hero['games'] * 100:.0f}%")
    if report.get("streak"):
        name, length = report["streak"]
        lines.append(f"🔥 Лучшая серия: {_b(name)} — {plural_wins(length)} подряд")
    shared = report.get("shared") or {}
    if shared.get("games"):
        lines.append(f"🤝 Вместе: {plural_games(shared['games'])} · {shared['wins']}–{shared['losses']}")

    lines += ["", "🏆 <b>Игроки</b>"]
    for i, r in enumerate(rows, start=1):
        meta = info.get(r["name"]) or {}
        rank = f" · {_esc(meta['rank_text'])}" if meta.get("rank_text") else ""
        mmr = f" · ≈{meta['mmr']}" if meta.get("mmr") is not None else ""
        top = r.get("hero")
        favorite = f" · {_esc(hero_name(top['hero_id']))} ×{top['games']}" if top else ""
        lines.append(f"{_pos(i)} {_b(r['name'])}{rank}{mmr}")
        lines.append(
            f"    {_today_delta(r['delta'])} · {r['wins']}–{r['losses']} ({r['winrate'] * 100:.0f}%) · "
            f"KDA {r['kda']:.2f} · {r['kills']}/{r['deaths']}/{r['assists']}{favorite}"
        )
    idle = [r["name"] for r in report["rows"] if not r["games"]]
    if idle:
        lines.append("💤 Не играли: " + ", ".join(_esc(name) for name in idle))

    picks = daily_record_picks(report.get("records") or [], 5)
    if picks:
        lines += ["", "🌟 <b>Рекорды суток</b>"]
        for r in picks:
            match = r["match"]
            lines.append(
                f"{r['emoji']} {_esc(r['text'])} — {_b(r['player'])} · {_esc(hero_name(match.get('hero_id')))} · "
                f'<a href="{dotabuff_match_url(match["match_id"])}">матч</a>'
            )
        lines.append("<i>Больше рекордов — /records</i>")
    best_game = render_daily_best_game(report.get("best_game"))
    if best_game:
        lines += ["", best_game]
    return "\n".join(lines)


def render_records(data: dict, period: str, tz: str = "UTC") -> str:
    """Рекорды пати за период: лучшая отдельная игра по каждому показателю (герой, значение, матч)."""
    title = f"🌟 <b>Рекорды пати {PERIOD_LABELS.get(period, '')}</b>"
    records = data.get("records") or []
    if not records:
        return title + "\n\n💤 За выбранный период нет данных (нужны сыгранные игры; GPM, урон и нетворт подгружаются фоном)."
    lines = [title, ""]
    for r in records:
        match = r["match"]
        date = fmt_local(match["start_time"], tz, "%d.%m.%y")
        lines.append(
            f"{r['emoji']} {r['title']}: {_b(r['player'])} — <b>{_esc(r['text'])}</b>\n"
            f"      {_esc(hero_name(match.get('hero_id')))} · {date} · "
            f'<a href="{dotabuff_match_url(match["match_id"])}">матч {match["match_id"]}</a>'
        )
    if data.get("streak"):
        name, length = data["streak"]
        lines.append(f"🔥 Лучшая серия побед: {_b(name)} — {length} подряд")
    return "\n".join(lines)


# --- настройки чата -----------------------------------------------------

def tz_label(tz_name: str) -> str:
    from mmrbot.keyboards import TIMEZONES
    for label, name in TIMEZONES:
        if name == tz_name:
            return f"{label} ({name})"
    return tz_name


def render_settings(chat) -> str:
    def state(flag: bool, on: str = "включены", off: str = "выключены") -> str:
        return on if flag else off

    return (
        "⚙️ <b>Настройки чата</b>\n\n"
        f"🎯 Шаг оценки MMR: <b>±{chat.mmr_step}</b> за ранкед-игру\n"
        f"⏰ Ежедневная сводка: <b>{chat.digest_hour:02d}:00</b> — "
        f"<b>{state(chat.notify_digest, 'включена', 'выключена')}</b> <i>(в дни без игр не приходит)</i>\n"
        f"🌍 Часовой пояс: <b>{_esc(tz_label(chat.tz))}</b>\n"
        f"🔔 Оповещения о смене ника/аватарки Steam: <b>{state(chat.notify_steam)}</b>\n"
        f"🎮 Оповещения о конце матча: <b>{state(chat.notify_games)}</b>\n"
        f"📅 Недельная сводка (понедельник): <b>{state(chat.notify_weekly, 'включена', 'выключена')}</b>\n"
        f"🖼 Отчёты: <b>{'текстом' if chat.prefer_text else 'картинками'}</b> <i>(рейтинг, матч, карточка игрока и др.; "
        f"«📝 Текстом» под картинкой работает всегда)</i>\n"
        f"🏷️ Теги участников с MMR: <b>{state(chat.tag_mmr)}</b> <i>(привязка: Пати → «Это я»)</i>\n"
        f"🔒 Менять настройки и удалять игроков в группе: "
        f"<b>{'только админы' if chat.admin_only else 'все участники'}</b>\n\n"
        "<i>Часовой пояс влияет на «сегодня» и время сводки.</i>"
    )


# --- герои игрока, роли, матч, герой ------------------------------------

PERIOD_LABELS = {"day": "за сутки", "week": "за неделю", "month": "за месяц", "year": "за год", "all": "за всё время"}
POSITION_NAMES = {1: "Pos 1 · Керри", 2: "Pos 2 · Мид", 3: "Pos 3 · Оффлейн",
                  4: "Pos 4 · Роумер", 5: "Pos 5 · Фулл-саппорт"}
POSITION_EMOJI = {1: "🗡️", 2: "🎯", 3: "🛡️", 4: "🧭", 5: "💚"}
LANE_LABELS = {"SAFE_LANE": "Лёгкая линия", "MID_LANE": "Мид", "OFF_LANE": "Оффлейн", "JUNGLE": "Лес"}


def _imp(value) -> str:
    if value is None:
        return "—"
    rounded = round(value)
    return f"{rounded:+d}" if rounded else "0"


def _wr_dot(winrate: float) -> str:
    """Цветная метка винрейта: 🟢 ≥55%, 🟡 48–54%, 🔴 ниже."""
    pct = winrate * 100
    return "🟢" if pct >= 55 else "🟡" if pct >= 48 else "🔴"


def _stat_line(s: dict) -> str:
    parts = [plural_games(s["games"]), f"{s['winrate'] * 100:.0f}%", f"KDA {s['kda']:.1f}"]
    if s.get("avg_imp") is not None:
        parts.append(f"IMP {_imp(s['avg_imp'])}")
    if s.get("avg_gpm") is not None:
        parts.append(f"GPM {s['avg_gpm']:.0f}")
    return " · ".join(parts)


def _stat_detail(s: dict) -> str:
    """Вторая строка блока: 🟢 винрейт · ⚔️ KDA · 📊 IMP · 💰 GPM (с отступом под эмодзи места)."""
    parts = [f"{_wr_dot(s['winrate'])} {s['winrate'] * 100:.0f}%", f"⚔️ KDA {s['kda']:.1f}"]
    if s.get("avg_imp") is not None:
        parts.append(f"📊 IMP {_imp(s['avg_imp'])}")
    if s.get("avg_gpm") is not None:
        parts.append(f"💰 GPM {s['avg_gpm']:.0f}")
    return "      " + " · ".join(parts)


def _stat_block(head: str, s: dict) -> str:
    return f"{head} · {plural_games(s['games'])}\n{_stat_detail(s)}"


def render_player_heroes(name: str, period: str, rows: list[dict], limit: int = 10) -> str:
    title = f"🦸 <b>Герои: {_esc(name)}</b> · <i>{PERIOD_LABELS.get(period, '')}</i>"
    if not rows:
        return title + "\n😴 За указанный период игр нет."
    blocks = [
        _stat_block(f"{_pos(i)} {_b(hero_name(s['hero_id']))}", s)
        for i, s in enumerate(rows[:limit], 1)
    ]
    text = title + "\n\n" + "\n".join(blocks)
    if len(rows) > limit:
        rest = len(rows) - limit
        text += f"\n\n➕ и ещё {rest} {plural_heroes(rest)}"
    return text


def render_roles(name: str, rows: list[dict], period: str = "all") -> str:
    title = f"🧭 <b>Позиции: {_esc(name)}</b> · <i>{PERIOD_LABELS.get(period, '')}</i>"
    if not rows:
        return title + "\n😴 Позиций пока нет. Нужны Stratz и сыгранные матчи."
    blocks = []
    for s in rows:
        emoji = POSITION_EMOJI.get(s["position"], "▫️")
        label = POSITION_NAMES.get(s["position"], "Pos " + str(s["position"]))
        blocks.append(_stat_block(f"{emoji} {_b(label)}", s))
    return title + "\n\n" + "\n".join(blocks)


def render_match_card(view: dict, tz: str = "UTC") -> str:
    from mmrbot.stats import is_win
    player, row = view["player"], view["match"]
    win = is_win(row["player_slot"], row["radiant_win"])
    when = fmt_local(row["start_time"], tz, "%d.%m %H:%M")
    duration = f" · {row['duration'] // 60} мин" if row.get("duration") else ""
    lines = [
        f"🎮 <b>Матч {row['match_id']}</b> <i>{when}{duration}</i>",
        f"{'🏆 Победа' if win else '💀 Поражение'} — {_b(player.display_name)} на {_b(hero_name(row.get('hero_id')))}",
        f"⚔️ K/D/A: {row.get('kills', 0)}/{row.get('deaths', 0)}/{row.get('assists', 0)}",
    ]
    if row.get("position"):
        role = POSITION_NAMES.get(row["position"], f"Pos {row['position']}")
        lane = LANE_LABELS.get(row.get("lane") or "")
        lines.append(f"🧭 Позиция: {role}" + (f" · {lane}" if lane else ""))
    if row.get("imp") is not None:
        lines.append(f"📊 IMP {_imp(row['imp'])}")
    farm = []
    if row.get("gpm") is not None:
        farm.append(f"GPM {row['gpm']:.0f}")
    if row.get("xpm") is not None:
        farm.append(f"XPM {row['xpm']:.0f}")
    if row.get("last_hits") is not None:
        farm.append(f"добивания {row['last_hits']}/{row.get('denies') or 0}")
    if row.get("net_worth") is not None:
        farm.append(f"нетворт {_k(row['net_worth'])}")
    if farm:
        lines.append("💰 Экономика: " + " · ".join(farm))
    dmg = []
    if row.get("hero_damage") is not None:
        dmg.append(f"урон {_k(row['hero_damage'])}")
    if row.get("tower_damage") is not None:
        dmg.append(f"башни {_k(row['tower_damage'])}")
    if row.get("hero_healing"):
        dmg.append(f"хил {_k(row['hero_healing'])}")
    if dmg:
        lines.append("💥 Влияние: " + " · ".join(dmg))
    if (row.get("leaver_status") or 0) >= 2:  # 2+ — отключился надолго / покинул / AFK: Dota считает такую игру иначе
        lines.append("🚪 Игрок покинул игру (отключение/AFK) — MMR за неё мог считаться иначе.")
    lines.append(f'🔗 <a href="{dotabuff_match_url(row["match_id"])}">Матч на Dotabuff</a>')
    return "\n".join(lines)


def render_hero_detail(hero_id: int, period: str, entries: list) -> str:
    title = f"🦸 <b>Герой: {_esc(hero_name(hero_id))}</b> · <i>{PERIOD_LABELS.get(period, '')}</i>"
    if not entries:
        return title + "\n😴 На данном герое участники пати не играли."
    blocks = [_stat_block(f"{_pos(i)} {_b(player.display_name)}", s) for i, (player, s) in enumerate(entries, 1)]
    return title + "\n\n" + "\n".join(blocks)


def _team_lines(players: list[dict], tracked: dict) -> list[str]:
    lines = []
    for p in sorted(players, key=lambda x: (x.get("position") or 9)):
        mark = "★ " if p.get("account_id") in tracked else ""
        name = tracked.get(p.get("account_id")) or p.get("name") or "—"
        pos = f"P{p['position']}" if p.get("position") else "—"
        lines.append(
            f"{mark}{_b(name)} · {_esc(hero_name(p.get('hero_id')))} "
            f"{p.get('kills') or 0}/{p.get('deaths') or 0}/{p.get('assists') or 0} · {pos} · IMP {_imp(p.get('imp'))}"
        )
    return lines


def render_full_match(match: dict, tracked: dict, focus=None, tz: str = "UTC") -> str:
    """Полный матч (все 10 игроков). tracked: {account_id: имя в боте} — отмечаются ★.

    focus — account_id игрока, чья подробная карточка (GPM, урон…) идёт сверху; без него — только шапка.
    """
    from types import SimpleNamespace
    players = match.get("players") or []
    radiant = [p for p in players if p["is_radiant"]]
    dire = [p for p in players if not p["is_radiant"]]
    target = next((p for p in players if p.get("account_id") == focus), None)
    if target is not None:
        row = dict(target, match_id=match["match_id"], start_time=match.get("start_time") or 0,
                   duration=match.get("duration"), radiant_win=match.get("radiant_win"),
                   player_slot=0 if target["is_radiant"] else 128)
        name = tracked.get(focus) or target.get("name") or "—"
        head = render_match_card({"player": SimpleNamespace(display_name=name), "match": row}, tz)
    else:
        when = fmt_local(match.get("start_time") or 0, tz, "%d.%m %H:%M")
        duration = f" · {match['duration'] // 60} мин" if match.get("duration") else ""
        head = (
            f"🎮 <b>Матч {match['match_id']}</b> <i>{when}{duration}</i>\n"
            f'🔗 <a href="{dotabuff_match_url(match["match_id"])}">Матч на Dotabuff</a>'
        )
    winner = "Radiant" if match.get("radiant_win") else "Dire"
    lines = [head, "", f"🏆 Победитель: {winner}", "🌕 <b>Radiant</b>"]
    lines += _team_lines(radiant, tracked)
    lines += ["🌑 <b>Dire</b>"] + _team_lines(dire, tracked)
    return "\n".join(lines)


def render_match_caption(match: dict, tracked: dict, focus=None, tz: str = "UTC") -> str:
    """Короткая подпись под картинкой матча: исход фокус-игрока (или победившая сторона) + шапка матча."""
    when = fmt_local(match.get("start_time") or 0, tz, "%d.%m %H:%M")
    duration = f" · {match['duration'] // 60} мин" if match.get("duration") else ""
    head = f"🎮 <b>Матч {match['match_id']}</b> <i>{when}{duration}</i>"
    me = next((p for p in match.get("players") or [] if focus is not None and p.get("account_id") == focus), None)
    if me is None:
        winner = "Radiant" if match.get("radiant_win") else "Dire"
        return f"{head}\n🏆 Победитель: {winner}"
    won = bool(me.get("is_radiant")) == bool(match.get("radiant_win"))
    name = tracked.get(focus) or me.get("name") or "—"
    kda = f"{me.get('kills') or 0}/{me.get('deaths') or 0}/{me.get('assists') or 0}"
    result = "🏆 Победа" if won else "💀 Поражение"
    return f"{result} — {_b(name)} на {_b(hero_name(me.get('hero_id')))} · {kda}\n{head}"
