"""Сезоны соревнования: сроки, зал славы и тексты (чистые функции, без сети и БД).

Сезон — окно времени, в котором считаются очки соревнования чата. По окончании итоги (чемпион и таблица очков)
сохраняются, а следующий сезон начинается с нуля: игры прошлых сезонов в новый зачёт не входят.
Зал славы собирается из сохранённых итогов — пересчитывать старые игры не нужно.
"""
from __future__ import annotations

import html
from typing import Optional

from mmrbot.timezones import to_local

DAY = 86_400
TABLE_LIMIT = 8  # сколько строк таблицы очков сохранять в итогах сезона
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def is_due(season, now: int) -> bool:
    """Сезону пора закончиться: идёт и плановый срок вышел."""
    return season.end_ts is None and now >= season.planned_end_ts


def days_left(season, now: int) -> int:
    """Сколько дней осталось (неполный день считается за день); 0 — срок вышел."""
    return max(0, -(-(season.planned_end_ts - now) // DAY))


def table_of(points: list[dict], limit: int = TABLE_LIMIT) -> list[dict]:
    """Итоговая таблица очков для хранения: [{player, points, golds}] от лучшего."""
    return [{"player": p["player"], "points": p["points"], "golds": p["golds"]} for p in points[:limit]]


def _ranks(table: list[dict]) -> list[int]:
    """Места по (очки, первые места): равные делят место (1, 1, 3)."""
    ranks: list[int] = []
    for i, row in enumerate(table):
        same = i and (row["points"], row["golds"]) == (table[i - 1]["points"], table[i - 1]["golds"])
        ranks.append(ranks[-1] if same else i + 1)
    return ranks


def hall_rows(finished: list) -> list[dict]:
    """Зал славы: у каждого призёра число титулов, вторых и третьих мест за все сезоны.

    Титул — только у единственного чемпиона сезона; при ничьей на первом месте его нет ни у кого. Серебро и бронза
    считаются по таблице очков. Порядок: титулы, серебро, бронза, ник.
    """
    stats: dict[str, dict] = {}

    def row(name: str) -> dict:
        return stats.setdefault(name, {"player": name, "titles": 0, "silver": 0, "bronze": 0})

    for season in finished:
        table = season.table or []
        for place, entry in zip(_ranks(table), table):
            if place == 1:
                if season.champion == entry["player"]:
                    row(entry["player"])["titles"] += 1
            elif place == 2:
                row(entry["player"])["silver"] += 1
            elif place == 3:
                row(entry["player"])["bronze"] += 1
    return sorted(stats.values(), key=lambda r: (-r["titles"], -r["silver"], -r["bronze"], r["player"]))


# --- тексты ---------------------------------------------------------------------------------------------------

def date_text(ts: int, tz: str) -> str:
    return to_local(ts, tz).strftime("%d.%m.%Y")


def _name(value: str) -> str:
    return f"<b>{html.escape(value)}</b>"


def span(season, tz: str) -> str:
    """«01.09.2026–30.09.2026» — для идущего сезона до планового срока."""
    return f"{date_text(season.start_ts, tz)}–{date_text(season.end_ts or season.planned_end_ts, tz)}"


def render_start(season, tz: str) -> str:
    return (
        f"🏁 <b>Сезон {season.number}</b> начался: до {date_text(season.planned_end_ts, tz)} ({season.length_days} дн.).\n"
        "Очки считаются только по играм сезона. Зачёт — /season, зал славы — /hall."
    )


def status_head(season, now: int, tz: str) -> str:
    left = days_left(season, now)
    return f"🏆 <b>Сезон {season.number}</b> · {span(season, tz)} · осталось {left} дн."


def status_caption(season, now: int, table: list[dict]) -> str:
    head = f"🏆 <b>Сезон {season.number}</b> · осталось {days_left(season, now)} дн."
    if not table:
        return head + "\nпока не с кем соревноваться"
    line = f"{head}\nлидер: {_name(table[0]['name'])} — {table[0]['points']} очк."
    if len(table) > 1:
        line += f" · дальше {html.escape(table[1]['name'])} ({table[1]['points']})"
    return line


def _champion_line(season, champion: Optional[dict], table: list[dict]) -> str:
    if champion is not None:
        return f"🏆 Чемпион: {_name(champion['player'])} — {champion['points']} очк."
    if not table:
        return "💤 Чемпиона нет: за сезон никто не играл."
    return "🤝 Чемпиона нет: первое место поделено."


def render_end(season, champion: Optional[dict], table: list[dict], nxt, tz: str) -> str:
    lines = [f"🏁 <b>Сезон {season.number} завершён</b> · {span(season, tz)}", _champion_line(season, champion, table)]
    ranks = _ranks(table)
    for place, entry in zip(ranks, table):
        if champion is not None and place == 1:
            continue
        lines.append(f"{MEDALS.get(place, '▫️')} {html.escape(entry['player'])} — {entry['points']} очк.")
    if nxt is not None:
        lines.append(f"\n🚀 <b>Сезон {nxt.number}</b> начался: до {date_text(nxt.planned_end_ts, tz)}. Зачёт — /season.")
    lines.append("Все сезоны — /hall.")
    return "\n".join(lines)


def end_caption(season, champion: Optional[dict], table: list[dict], nxt) -> str:
    line = f"🏁 <b>Сезон {season.number} завершён</b>\n{_champion_line(season, champion, table)}"
    if nxt is not None:
        line += f"\n🚀 Сезон {nxt.number} начался"
    return line


def render_hall(finished: list, tz: str) -> str:
    """Зал славы: призёры за все сезоны и список сезонов с чемпионами."""
    head = "🏛 <b>Зал славы</b>"
    if not finished:
        return f"{head}\n\nПока пусто: ни один сезон ещё не завершён. Начать сезон: /season start"
    lines = [head, ""]
    for entry in hall_rows(finished):
        parts = [f"🏆 {entry['titles']}"] if entry["titles"] else []
        parts += [f"🥈 {entry['silver']}"] if entry["silver"] else []
        parts += [f"🥉 {entry['bronze']}"] if entry["bronze"] else []
        lines.append(f"{html.escape(entry['player'])} — " + " · ".join(parts))
    lines += ["", "<b>Сезоны</b>"]
    for season in reversed(finished):
        top = season.table[0] if season.table else None
        who = f"{_name(season.champion)} ({top['points']} очк.)" if season.champion and top else "чемпиона нет"
        lines.append(f"🏆 Сезон {season.number} · {span(season, tz)}: {who}")
    return "\n".join(lines)
