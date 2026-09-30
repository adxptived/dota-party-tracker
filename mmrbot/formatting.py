"""Рендер сообщений бота — карточный дизайн, Telegram HTML.

Сообщения-борды (лидерборд, награды, совместка, герои, карточка игрока, список)
отправляются с parse_mode=HTML — имена экранируются через html.escape.
Обычные подтверждения/ошибки шлются обычным текстом (без разметки).
"""
from __future__ import annotations

import html
from typing import Optional

from mmrbot.heroes import hero_name
from mmrbot.storage import Player
from mmrbot.tracker import PlayerSummary, compute_awards

POSITIONS = {1: "🥇", 2: "🥈", 3: "🥉"}
LANE_NAMES = {1: "Safe", 2: "Mid", 3: "Off", 4: "Лес"}


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


def _rank_with_emoji(s: PlayerSummary) -> str:
    prefix = f"{s.rank_emoji} " if s.rank_emoji else ""
    return f"{prefix}{s.rank}"


def _streak_str(s: PlayerSummary) -> str:
    if s.streak_len < 2:
        return ""
    return f"  🔥{s.streak_len} подряд" if s.streak_type == "W" else f"  💧{s.streak_len} подряд"


def _heroes_line(top_heroes: list[dict]) -> str:
    if not top_heroes:
        return "нет данных"
    return ", ".join(
        f"{_esc(hero_name(h['hero_id']))} ({h['games']}и, {h['winrate'] * 100:.0f}%)" for h in top_heroes
    )


def _fmt_wr(games: int, wins: int) -> str:
    if not games:
        return "—"
    return f"{wins}–{games - wins} ({wins / games * 100:.0f}%)"


# --- лидерборд ----------------------------------------------------------

def _card_full(index: int, s: PlayerSummary) -> str:
    lines = [f"{_pos(index)} {_b(s.display_name)}"]
    lines.append(f"    {_rank_with_emoji(s)} · {_b(_mmr_str(s.current_mmr))}{_trend(s.mmr_delta)}")
    if s.games_total == 0:
        lines.append("    пока без игр")
    else:
        lines.append(
            f"    {plural_games(s.games_total)} · {s.wins_total}–{s.losses_total} "
            f"({s.winrate * 100:.0f}%) · KDA {s.kda_ratio:.2f}{_streak_str(s)}"
        )
        if s.games_today:
            lines.append(
                f"    сегодня: {plural_games(s.games_today)}, "
                f"{_today_delta(s.delta_today)} ({s.wins_today}–{s.losses_today})"
            )
    return "\n".join(lines)


def _card_today(index: int, s: PlayerSummary) -> str:
    lines = [f"{_pos(index)} {_b(s.display_name)} · {_rank_with_emoji(s)}"]
    if s.games_today == 0:
        lines.append("    сегодня без игр")
    else:
        lines.append(
            f"    сегодня: {plural_games(s.games_today)}, "
            f"{_today_delta(s.delta_today)} ({s.wins_today}–{s.losses_today})"
        )
    return "\n".join(lines)


def render_leaderboard(summaries: list[PlayerSummary], today_only: bool = False) -> str:
    if not summaries:
        return (
            "В этом чате пока нет отслеживаемых игроков.\n"
            "Добавь аккаунт: /add «ссылка Dotabuff/OpenDota или ID» Имя [стартовый_MMR]\n"
            "Например: /add dotabuff.com/players/123456 Вася 5400"
        )

    if today_only:
        header = "📅 <b>Сегодня</b> · ранкед"
        blocks = [_card_today(i, s) for i, s in enumerate(summaries, start=1)]
        return header + "\n\n" + "\n\n".join(blocks)

    header = "🏆 <b>Лидерборд пати</b>\n<i>ранкед с момента добавления</i>"
    blocks = [_card_full(i, s) for i, s in enumerate(summaries, start=1)]
    footer = "\n<i>≈ MMR — оценка (±шаг за игру), точного Dota не отдаёт. /help — команды</i>"
    return header + "\n\n" + "\n\n".join(blocks) + "\n" + footer


# --- награды ------------------------------------------------------------

def render_awards(summaries: list[PlayerSummary]) -> str:
    awards = compute_awards(summaries)
    if not awards:
        return ""
    lines = ["🎖 <b>Награды пати:</b>"]
    for award in awards:
        lines.append(f"{award['title']} — {_b(award['player'])} ({_esc(award['detail'])})")
    return "\n".join(lines)


# --- совместная игра ----------------------------------------------------

def render_together(result: dict) -> str:
    summary = result.get("summary", {})
    games = summary.get("games", 0)
    if games == 0:
        return (
            "🤝 <b>Совместная игра пати</b>\n\n"
            "Пока нет совместных ранкед-игр (или данные ещё собираются).\n"
            "Как сыграете вместе — покажу общий винрейт и лучшее дуо."
        )
    lines = [
        "🤝 <b>Совместная игра пати</b>",
        "",
        f"Вместе сыграно: {_b(plural_games(games))} · {_fmt_wr(games, summary.get('wins', 0))}",
    ]
    duo = result.get("duo")
    if duo:
        n1, n2 = duo["pair"]
        lines.append(
            f"👯 Лучшее дуо: <b>{_esc(n1)} + {_esc(n2)}</b> — "
            f"{plural_games(duo['games'])}, {_fmt_wr(duo['games'], duo['wins'])}"
        )
    return "\n".join(lines)


# --- герои --------------------------------------------------------------

def render_heroes(summaries: list[PlayerSummary]) -> str:
    if not summaries:
        return "Нет игроков. Добавь: /add «ссылка или ID» Имя [MMR]"
    lines = ["🦸 <b>Топ героев участников:</b>"]
    for s in summaries:
        lines.append(f"• {_b(s.display_name)}: {_heroes_line(s.top_heroes)}")
    return "\n".join(lines)


# --- карточка игрока ----------------------------------------------------

def _k(value) -> str:
    """Компактно: 13656 → 13.7k, 428 → 428."""
    if value is None:
        return "—"
    return f"{value / 1000:.1f}k" if value >= 1000 else f"{value:.0f}"


def _form_icons(form: list) -> str:
    return "".join("✅" if won else "❌" for won in form)


def _wr_ratio(pair: tuple) -> Optional[float]:
    games, wins = pair
    return wins / games if games else None


def render_player_card(s: PlayerSummary) -> str:
    """Карточка игрока — ТОЛЬКО окно отслеживания (последние игры), без карьерных срезов."""
    header = f"🎮 {_b(s.display_name)} · {_rank_with_emoji(s)}{_streak_str(s)}"
    if s.games_total == 0:
        return header + "\nпока без ранкед-игр с момента добавления"

    lines = [header, f"📅 <i>Последние {plural_games(s.games_total)}</i>", ""]

    # Заголовочная строка: MMR + честный перф рядом.
    perf = f"    🎯 {_b(f'{s.avg_perf * 100:.0f}/100')} перф" if s.avg_perf is not None else ""
    lines.append(f"{_b(_mmr_str(s.current_mmr))}{_trend(s.mmr_delta)}{perf}")
    lines.append(f"{s.wins_total}–{s.losses_total} ({s.winrate * 100:.0f}%)   форма {_form_icons(s.recent_form)}")

    # Бой + экономика (всё за окно).
    lines.append(f"⚔️ KDA {s.kda_ratio:.2f} ({s.avg_kills:.0f}/{s.avg_deaths:.0f}/{s.avg_assists:.0f})")
    econ = []
    if s.avg_gpm_window is not None:
        econ.append(f"{s.avg_gpm_window:.0f} gpm")
    if s.avg_net_worth_window is not None:
        econ.append(f"{_k(s.avg_net_worth_window)} нетворт")
    if s.avg_hero_damage_window is not None:
        econ.append(f"{_k(s.avg_hero_damage_window)} урон")
    if econ:
        lines.append("💰 " + " · ".join(econ))

    lines.append("")

    # Разрезы + подсказки.
    solo_wr, party_wr = _wr_ratio(s.solo), _wr_ratio(s.party)
    note = ""
    if solo_wr is not None and party_wr is not None and s.party[0] >= 2 and party_wr < solo_wr - 0.2:
        note = "   ← в стаке слабее"
    lines.append(f"🧑‍🤝‍🧑 соло {_fmt_wr(*s.solo)} · пати {_fmt_wr(*s.party)}{note}")

    if s.best_hour and s.worst_hour:
        bh, bwr = s.best_hour
        wh, wwr = s.worst_hour
        lines.append(f"🌙 лучший час {bh:02d}:00 ({bwr * 100:.0f}%) · худший {wh:02d}:00 ({wwr * 100:.0f}%)")
    if s.avg_duration_min:
        lines.append(f"⏱️ средняя игра {s.avg_duration_min:.0f} мин (макс {s.max_duration_min:.0f})")
    if s.best_game:
        bg = s.best_game
        lines.append(
            f"🌟 топ-игра: {_esc(hero_name(bg['hero_id']))} {bg['kills']}/{bg['deaths']}/{bg['assists']}"
        )
    if s.longest_win_streak >= 2:
        lines.append(f"🔥 макс серия побед: {s.longest_win_streak}")
    lines.append(f"🦸 {_heroes_line(s.top_heroes)}")

    lines.append("")
    lines.append("<i>перф = перцентиль vs тот же герой (честно к роли)</i>")
    return "\n".join(lines)


# --- список игроков -----------------------------------------------------

def render_player_list(players: list[Player]) -> str:
    if not players:
        return "Список пуст. Добавь игрока: /add «ссылка или ID» Имя [MMR]"
    lines = ["👥 <b>Отслеживаемые игроки:</b>"]
    for p in players:
        mmr = f"старт MMR ≈ {p.anchor_mmr}" if p.anchor_mmr is not None else "MMR не задан"
        lines.append(f"• {_b(p.display_name)} (id {p.account_id}) — {mmr}")
    return "\n".join(lines)
