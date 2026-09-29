"""Рендер сообщений бота (русский, plain text — безопасно для Telegram без разметки)."""
from __future__ import annotations

from typing import Optional

from mmrbot.storage import Player
from mmrbot.tracker import PlayerSummary


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
    lines = [f"{index}. {s.display_name} — {s.rank}"]
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


def render_player_list(players: list[Player]) -> str:
    if not players:
        return "Список пуст. Добавь игрока: /add <ссылка или ID> Имя [MMR]"
    lines = ["👥 Отслеживаемые игроки:"]
    for p in players:
        mmr = f"старт MMR ≈ {p.anchor_mmr}" if p.anchor_mmr is not None else "MMR не задан"
        lines.append(f"• {p.display_name} (id {p.account_id}) — {mmr}")
    return "\n".join(lines)
