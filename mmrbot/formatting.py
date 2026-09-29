"""Рендер сообщений бота (русский, plain text — безопасно для Telegram без разметки)."""
from __future__ import annotations

from typing import Optional

from mmrbot.heroes import hero_name
from mmrbot.storage import Player
from mmrbot.tracker import PlayerSummary, compute_awards


def _streak_str(summary: PlayerSummary) -> str:
    if summary.streak_len < 2:
        return ""
    if summary.streak_type == "W":
        return f"  🔥{summary.streak_len} побед подряд"
    return f"  💧{summary.streak_len} поражений подряд"


def format_delta(delta: int) -> str:
    if delta > 0:
        return f"+{delta}"
    if delta < 0:
        return str(delta)  # уже с минусом
    return "0"


def _format_mmr(current: Optional[int], delta: int) -> str:
    if current is not None:
        return f"≈ {current} ({format_delta(delta)})"
    return f"≈ ? ({format_delta(delta)} за сессию)"


def _format_kda(s: PlayerSummary) -> str:
    return f"KDA {s.kda_ratio:.2f} ({s.avg_kills:.1f}/{s.avg_deaths:.1f}/{s.avg_assists:.1f})"


def _summary_block(index: int, s: PlayerSummary, today_only: bool) -> str:
    lines = [f"{index}. {s.display_name} — {s.rank}{'' if today_only else _streak_str(s)}"]
    if today_only:
        if s.games_today == 0:
            lines.append("   сегодня без игр")
        else:
            lines.append(
                f"   сегодня: {s.games_today} игр, MMR {format_delta(s.delta_today)} "
                f"({s.wins_today}–{s.losses_today})"
            )
    else:
        lines.append(
            f"   MMR {_format_mmr(s.current_mmr, s.mmr_delta)} · игр {s.games_total} · "
            f"{s.wins_total}–{s.losses_total} ({s.winrate * 100:.0f}%) · {_format_kda(s)}"
        )
        if s.games_today:
            lines.append(f"   сегодня: {s.games_today} игр, MMR {format_delta(s.delta_today)} ({s.wins_today}–{s.losses_today})")
    return "\n".join(lines)


def render_leaderboard(summaries: list[PlayerSummary], today_only: bool = False) -> str:
    if not summaries:
        return (
            "В этом чате пока нет отслеживаемых игроков.\n"
            "Добавь аккаунт: /add <ссылка Dotabuff/OpenDota или ID> Имя [стартовый_MMR]\n"
            "Например: /add dotabuff.com/players/123456 Вася 5400"
        )

    header = "📅 Сегодня (ранкед)" if today_only else "🏆 Лидерборд пати (ранкед с момента добавления)"
    blocks = [_summary_block(i, s, today_only) for i, s in enumerate(summaries, start=1)]
    footer = "\n\nMMR — оценка (±шаг за игру), точного числа Dota 2 не отдаёт. Коррекция: /setmmr Имя MMR"
    return header + "\n\n" + "\n\n".join(blocks) + footer


def _fmt_wr(games: int, wins: int) -> str:
    if not games:
        return "—"
    return f"{wins}–{games - wins} ({wins / games * 100:.0f}%)"


def render_awards(summaries: list[PlayerSummary]) -> str:
    awards = compute_awards(summaries)
    if not awards:
        return ""
    lines = ["🎖 Награды пати:"]
    for award in awards:
        lines.append(f"{award['title']} — {award['player']} ({award['detail']})")
    return "\n".join(lines)


def render_together(result: dict) -> str:
    summary = result.get("summary", {})
    games = summary.get("games", 0)
    if games == 0:
        return (
            "🤝 Совместная игра пати\n\n"
            "Пока нет совместных ранкед-игр (или данные ещё собираются).\n"
            "Как сыграете вместе — тут появится общий винрейт и лучшее дуо."
        )
    lines = [
        "🤝 Совместная игра пати",
        "",
        f"Вместе сыграно: {games} игр, {_fmt_wr(games, summary.get('wins', 0))}",
    ]
    duo = result.get("duo")
    if duo:
        n1, n2 = duo["pair"]
        lines.append(f"👯 Лучшее дуо: {n1} + {n2} — {duo['games']} игр, {_fmt_wr(duo['games'], duo['wins'])}")
    return "\n".join(lines)


def _heroes_line(top_heroes: list[dict]) -> str:
    if not top_heroes:
        return "нет данных"
    parts = [f"{hero_name(h['hero_id'])} ({h['games']}и, {h['winrate'] * 100:.0f}%)" for h in top_heroes]
    return ", ".join(parts)


def render_heroes(summaries: list[PlayerSummary]) -> str:
    if not summaries:
        return "Нет игроков. Добавь: /add <ссылка или ID> Имя [MMR]"
    lines = ["🦸 Топ героев участников:"]
    for s in summaries:
        lines.append(f"• {s.display_name}: {_heroes_line(s.top_heroes)}")
    return "\n".join(lines)


def render_player_card(s: PlayerSummary) -> str:
    lines = [f"🎮 {s.display_name} — {s.rank}{_streak_str(s)}"]
    lines.append(f"MMR {_format_mmr(s.current_mmr, s.mmr_delta)} · игр {s.games_total} · "
                 f"{s.wins_total}–{s.losses_total} ({s.winrate * 100:.0f}%)")
    lines.append(f"{_format_kda(s)}")

    econ = []
    if s.gpm is not None:
        econ.append(f"GPM {s.gpm:.0f}")
    if s.xpm is not None:
        econ.append(f"XPM {s.xpm:.0f}")
    if s.last_hits is not None:
        econ.append(f"LH/игра {s.last_hits:.0f}")
    if econ:
        lines.append("💰 " + " · ".join(econ))

    if s.avg_duration_min:
        lines.append(f"⏱️ Средняя игра {s.avg_duration_min:.0f} мин (макс {s.max_duration_min:.0f})")

    lines.append(f"🧑‍🤝‍🧑 Соло {_fmt_wr(*s.solo)} · Пати {_fmt_wr(*s.party)}")

    if s.best_hour and s.worst_hour:
        bh, bwr = s.best_hour
        wh, wwr = s.worst_hour
        lines.append(f"🌙 Лучший час {bh:02d}:00 ({bwr * 100:.0f}%) · худший {wh:02d}:00 ({wwr * 100:.0f}%)")

    lines.append(f"🦸 Герои: {_heroes_line(s.top_heroes)}")
    return "\n".join(lines)


def render_player_list(players: list[Player]) -> str:
    if not players:
        return "Список пуст. Добавь игрока: /add <ссылка или ID> Имя [MMR]"
    lines = ["👥 Отслеживаемые игроки:"]
    for p in players:
        mmr = f"старт MMR ≈ {p.anchor_mmr}" if p.anchor_mmr is not None else "MMR не задан"
        lines.append(f"• {p.display_name} (id {p.account_id}) — {mmr}")
    return "\n".join(lines)
