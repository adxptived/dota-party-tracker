"""Данные доменных сводок → описания строк, плиток и подписей для карточек-картинок (чистые функции).

Рисуют карточки stats_image.py и др.; здесь — только «что показать»: текст, цвета, порядок. Сети и БД нет.
"""
from __future__ import annotations

import html
from typing import Optional

from mmrbot.cards import GOLD, MUTED, clean, delta_color, signed
from mmrbot.formatting import PULSE_RECORDS, plural_games


def _esc(text) -> str:
    return html.escape(clean(text) or "Игрок")


def summary_rows(summaries: list, today: bool) -> list[dict]:
    """Строки таблицы рейтинга: `today=False` — всего (с начала отслеживания), `True` — сегодня."""
    rows = []
    for s in summaries:
        top = s.top_heroes[0] if s.top_heroes else None
        if today:
            delta = s.delta_today
            if s.games_today:
                sub, color = f"{signed(delta)} сегодня", delta_color(delta)
            else:
                sub, color = "сегодня игр не было", MUTED
            wins, losses = s.wins_today, s.losses_today
        else:
            delta = s.mmr_delta
            if s.games_total and s.anchor_games:
                sub, color = f"{signed(delta)} за {plural_games(s.anchor_games)}", delta_color(delta)
            elif s.history_closed:
                sub, color = "история закрыта", MUTED
            else:
                sub, color = None, MUTED
            wins, losses = s.wins_total, s.losses_total
        if not s.games_total and s.history_closed and not today:
            sub, color = "история закрыта", MUTED
        rows.append({
            "name": s.display_name, "avatar": s.avatar, "rank_tier": s.rank_tier, "rank_text": s.rank,
            "big": f"≈{s.current_mmr}" if s.current_mmr is not None else "—", "big_color": None,
            "sub": sub, "sub_color": color, "wins": wins, "losses": losses, "form": list(s.form_long or []),
            "hero_id": top["hero_id"] if top else None, "hero_note": f"×{top['games']}" if top else "",
        })
    return rows


def period_rows(rows: list[dict], info: Optional[dict] = None) -> list[dict]:
    """Строки таблицы за неделю/месяц: крупно — оценка ±MMR за период; ник/аватар/ранг — из `info` по имени."""
    info = info or {}
    out = []
    for r in rows:
        extra = info.get(r["name"], {})
        if r["games"]:
            big, sub = signed(r["delta"]), f"{plural_games(r['games'])} · KDA {r['kda']:.2f}"
        else:
            big, sub = "0", "игр не было"
        out.append({
            "name": r["name"], "avatar": extra.get("avatar"), "rank_tier": extra.get("rank_tier"),
            "rank_text": extra.get("rank_text") or "", "big": big, "big_color": delta_color(r["delta"]) if r["games"] else MUTED,
            "sub": sub, "sub_color": MUTED, "wins": r["wins"], "losses": r["losses"], "form": [],
            "hero_id": None, "hero_note": "",
        })
    return out


def _wr(games: int, wins: int) -> str:
    return f"{wins}–{games - wins} ({round(wins * 100 / games)}%)"


def party_tiles(summaries: list, week_rows: list[dict]) -> list[dict]:
    """Плитки «Стата пати»: сегодня, за неделю, лидер недели (как строки «Пульса» в тексте)."""
    tiles = []
    t_games = sum(s.games_today for s in summaries)
    if t_games:
        t_wins = sum(s.wins_today for s in summaries)
        t_delta = sum(s.delta_today for s in summaries)
        tiles.append({"label": "Сегодня", "value": plural_games(t_games), "sub": f"{_wr(t_games, t_wins)} · {signed(t_delta)}",
                      "color": delta_color(t_delta)})
    else:
        tiles.append({"label": "Сегодня", "value": "игр нет", "sub": None, "color": MUTED})
    played = [r for r in week_rows if r["games"] > 0]
    if played:
        w_games = sum(r["games"] for r in played)
        w_wins = sum(r["wins"] for r in played)
        w_delta = sum(r["delta"] for r in played)
        tiles.append({"label": "За неделю", "value": plural_games(w_games), "sub": f"{_wr(w_games, w_wins)} · {signed(w_delta)}",
                      "color": delta_color(w_delta)})
        best = max(played, key=lambda r: r["delta"])
        if len(played) >= 2 and best["delta"] > 0:
            tiles.append({"label": "Лидер недели", "value": clean(best["name"]), "sub": f"{signed(best['delta'])} ({best['wins']}–{best['losses']})",
                          "color": GOLD})
    else:
        tiles.append({"label": "За неделю", "value": "игр нет", "sub": None, "color": MUTED})
    return tiles


def record_items(week_records: dict) -> list[dict]:
    """Рекорды недели для «Пульса» (gpm, убийства, IMP) — с героем для иконки."""
    items = []
    for r in (week_records or {}).get("records", []):
        if r["key"] in PULSE_RECORDS:
            items.append({"label": r["title"], "value": r["text"], "player": r["player"],
                          "hero_id": (r.get("match") or {}).get("hero_id")})
    return items


def award_items(awards: list[dict]) -> list[dict]:
    return [{"title": a["title"], "player": a["player"], "detail": a["detail"]} for a in awards]


def leader_caption(summaries: list, week_rows: list[dict], mode: str) -> str:
    """Подпись под рейтингом: «🏆 Рейтинг · Лидер: Вася ≈5420 (+75 за неделю)»; для «Сегодня» — лидер дня."""
    if mode == "today":
        played = [s for s in summaries if s.games_today]
        head = "📅 <b>Статистика за сегодня</b>"
        if not played:
            return head + " · игр пока не было"
        best = max(played, key=lambda s: (s.delta_today, s.wins_today))
        return f"{head} · Лидер: <b>{_esc(best.display_name)}</b> {signed(best.delta_today)} ({best.wins_today}–{best.losses_today})"
    head = "🏆 <b>Рейтинг</b>"
    if not summaries:
        return head
    leader = summaries[0]
    week = next((r for r in week_rows if r["name"] == leader.display_name and r["games"]), None)
    if week is not None:
        note = f"{signed(week['delta'])} за неделю"
    elif leader.games_total and leader.anchor_games:
        note = f"{signed(leader.mmr_delta)} за {plural_games(leader.anchor_games)}"
    else:
        note = ""
    mmr = f" ≈{leader.current_mmr}" if leader.current_mmr is not None else ""
    return f"{head} · Лидер: <b>{_esc(leader.display_name)}</b>{mmr}" + (f" ({note})" if note else "")


def period_caption(rows: list[dict], period: str) -> str:
    emoji, title = ("📆", "За месяц") if period == "month" else ("🗓️", "За неделю")
    head = f"{emoji} <b>{title}</b>"
    played = [r for r in rows if r["games"]]
    if not played:
        return head + " · игр не было"
    best = played[0]  # строки уже отсортированы: сверху лучший по дельте
    return f"{head} · Лидер: <b>{_esc(best['name'])}</b> {signed(best['delta'])} ({best['wins']}–{best['losses']})"
