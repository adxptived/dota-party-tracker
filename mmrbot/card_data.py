"""Данные доменных сводок → описания строк, плиток и подписей для карточек-картинок (чистые функции).

Рисуют карточки stats_image.py и др.; здесь — только «что показать»: текст, цвета, порядок. Сети и БД нет.
"""
from __future__ import annotations

import html
from typing import Optional

from mmrbot.cards import ACCENT, GOLD, MUTED, WIN, clean, delta_color, signed
from mmrbot.formatting import (
    PERIOD_LABELS, POSITION_NAMES, PULSE_RECORDS, best_game_stats, daily_record_picks, fmt_local,
    fmt_window, local_time, plural_games, plural_heroes, plural_wins,
)
from mmrbot.heroes import hero_name


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
            "streak": (s.streak_type, s.streak_len) if s.streak_len >= 3 else None,
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


def leader_caption(summaries: list, mode: str) -> str:
    """Подпись под рейтингом: «🏆 Рейтинг · Лидер: Вася ≈5420»; для «Сегодня» — лидер дня."""
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
    mmr = f" ≈{leader.current_mmr}" if leader.current_mmr is not None else ""
    return f"{head} · Лидер: <b>{_esc(leader.display_name)}</b>{mmr}"


def period_caption(rows: list[dict], period: str) -> str:
    emoji, title = ("📆", "За месяц") if period == "month" else ("🗓️", "За неделю")
    head = f"{emoji} <b>{title}</b>"
    played = [r for r in rows if r["games"]]
    if not played:
        return head + " · игр не было"
    best = played[0]  # строки уже отсортированы: сверху лучший по дельте
    return f"{head} · Лидер: <b>{_esc(best['name'])}</b> {signed(best['delta'])} ({best['wins']}–{best['losses']})"


# --- карточка игрока ----------------------------------------------------------------------------

def _k(value) -> str:
    if value is None:
        return "—"
    return f"{value / 1000:.1f}k" if value >= 1000 else f"{value:.0f}"


def _last_game_stats(game: dict) -> list[tuple[str, str]]:
    """Подробности последней игры ячейками (подпись, значение) — только то, что уже загружено."""
    cells = []
    if game.get("duration"):
        cells.append(("Время", f"{game['duration'] // 60} мин"))
    if game.get("gpm"):
        cells.append(("GPM", f"{game['gpm']:.0f}"))
    if game.get("hero_damage"):
        cells.append(("Урон", _k(game["hero_damage"])))
    return cells


def _position_tile(s) -> dict:
    """Шестая плитка карточки: основная позиция (Stratz); её нет — игровая роль; нет и её — средняя длительность игры."""
    if s.main_position:
        pos, pos_games, known = s.main_position
        label = "Саппорт" if pos == 5 else POSITION_NAMES.get(pos, "").split("·")[-1].strip()  # плитка узкая
        share = f"{round(pos_games * 100 / known)}% игр" if known else ""
        return {"label": "Позиция", "value": f"Pos {pos}", "sub": " · ".join(x for x in (label, share) if x)}
    if s.role_style:
        return {"label": "Роль", "value": s.role_style.replace("/", "(").split("(")[0].strip().capitalize(), "sub": "по фарму и лечению"}
    return {"label": "Средняя игра", "value": f"{s.avg_duration_min:.0f} мин" if s.avg_duration_min else "—", "sub": None}


def _partial(known: Optional[int], games: int) -> Optional[str]:
    """«по 40 из 56» — показатель известен не по всем играм; иначе подписи нет."""
    return f"по {known} из {games}" if known is not None and 0 < known < games else None


def _facts(s) -> list[tuple]:
    """Короткие факты под «Соло и группа»: самая длинная серия побед, широта пула героев, средняя длина игры.

    Раньше здесь были «лучший/худший час» — по трём играм в час это шум, а не закономерность.
    """
    facts = []
    if s.longest_win_streak >= 2:
        facts.append(("Лучшая серия", plural_wins(s.longest_win_streak), WIN))
    if s.hero_pool:
        facts.append(("Пул героев", f"{s.hero_pool} {plural_heroes(s.hero_pool)}", None))
    if s.avg_duration_min:
        facts.append(("Средняя игра", f"{s.avg_duration_min:.0f} мин", None))
    return facts


def recent_items(games: list, tz: str = "UTC") -> list[dict]:
    """Последние игры для ленты на карточке: герой, исход, K/D/A, ±MMR, длительность и дата."""
    from mmrbot.heroes import hero_name
    return [{"hero_id": g.get("hero_id"), "name": hero_name(g.get("hero_id")), "won": bool(g.get("won")),
             "kills": g.get("kills") or 0, "deaths": g.get("deaths") or 0, "assists": g.get("assists") or 0,
             "delta": g.get("delta"), "double_down": bool(g.get("double_down")), "level": g.get("level"),
             "plus_xp": g.get("plus_xp"),
             "minutes": round(g["duration"] / 60) if g.get("duration") else None,
             "when": fmt_local(g["start_time"], tz, "%d.%m") if g.get("start_time") else None} for g in games]


def player_card(s, standing: Optional[dict] = None, series: Optional[list] = None, note: Optional[str] = None,
                absolute: bool = False, tz: str = "UTC") -> dict:
    """Сводка игрока → описание карточки для player_image.render_player_image.

    standing — запись игрока из tracker.build_chat_comparison()["players"][имя] (+ size); series — значения линии
    по играм (последние ~60): при absolute=True — готовая оценка MMR после каждой игры (stats.mmr_timeline),
    иначе накопленные ±MMR, к которым прибавляется стартовый MMR; note — пометка об устаревании данных;
    tz — часовой пояс чата (время последней игры).
    """
    from mmrbot.ranks import rank_label

    games = s.games_total
    card: dict = {
        "name": s.display_name, "steam_name": s.steam_name, "avatar": s.avatar, "rank_tier": s.rank_tier,
        "rank_text": s.rank, "mmr_text": f"≈{s.current_mmr}" if s.current_mmr is not None else "≈ ?",
        "mmr_delta": s.mmr_delta if games and s.anchor_games else None,
        "delta_note": f"за {plural_games(s.anchor_games)}" if s.anchor_games else "",
        "perf": round(s.avg_perf * 100) if s.avg_perf is not None else None,
        "streak": (s.streak_type, s.streak_len) if s.streak_len >= 2 else None,
        "warnings": [], "note": note,
    }
    if s.mmr_drift:
        card["warnings"].append(f"Оценка MMR расходится с медалью {s.rank} — обновите стартовый: /setmmr")
    if s.history_closed:
        card["warnings"].append("История матчей закрыта у OpenDota — игры могли не загрузиться, цифры неполные.")
    if not games:
        card["warnings"].append("Ранкед-игр с момента добавления пока нет.")
        return card

    damage_games = s.damage_games if s.damage_games is not None else s.detail_games
    card["tiles"] = [
        {"label": "Результат", "value": f"{s.wins_total}–{s.losses_total}", "sub": f"{s.winrate * 100:.0f}% винрейт",
         "color": delta_color((s.winrate - 0.5) * 100)},
        {"label": "KDA", "value": f"{s.kda_ratio:.2f}", "sub": f"{s.avg_kills:.0f}/{s.avg_deaths:.0f}/{s.avg_assists:.0f}"},
        {"label": "GPM", "value": f"{s.avg_gpm_window:.0f}" if s.avg_gpm_window is not None else "—",
         "sub": _partial(s.detail_games, games)},
        {"label": "Урон по героям", "value": _k(s.avg_hero_damage_window), "sub": _partial(damage_games, games)},
        _position_tile(s),
    ]
    values = list(series or [])
    if values:
        base = 0 if absolute else s.anchor_mmr or 0
        card["series"] = [base + v for v in values] if s.anchor_mmr is not None else values
        card["series_label"] = f"Динамика ≈MMR · последние {plural_games(len(values))}" if s.anchor_mmr is not None \
            else f"Динамика ±MMR · последние {plural_games(len(values))}"
    card["form"] = list(s.form_long or [])
    card["split"] = [{"label": label, "wins": pair[1], "losses": pair[0] - pair[1]}
                     for label, pair in (("Соло", s.solo), ("В группе", s.party)) if pair[0]]
    card["facts"] = _facts(s)
    from mmrbot.heroes import hero_name
    card["heroes"] = [{"hero_id": h["hero_id"], "name": hero_name(h["hero_id"]), "games": h["games"], "wins": h["wins"],
                       "winrate": h["winrate"], "kda": h.get("kda")} for h in s.top_heroes]
    if s.last_game:
        lg = s.last_game
        card["last_game"] = {"hero_id": lg["hero_id"], "name": hero_name(lg["hero_id"]), "kills": lg["kills"],
                             "deaths": lg["deaths"], "assists": lg["assists"], "kda": lg["kda"], "won": lg["won"],
                             "when": fmt_local(lg["start_time"], tz, "%d.%m %H:%M") if lg.get("start_time") else None,
                             "stats": _last_game_stats(lg), "level": lg.get("level"), "plus_xp": lg.get("plus_xp")}
    card["recent"] = recent_items(s.recent_games or [], tz)
    card["recent_mmr"] = s.anchor_mmr is not None  # ±MMR за игру — только если MMR игрока задан
    if s.lobby_rank:
        card["lobby_rank"], card["lobby_text"] = s.lobby_rank, rank_label(s.lobby_rank)
    if standing and standing.get("size", 0) >= 2 and standing.get("power_rank"):
        card["standing"] = f"#{standing['power_rank']} из {standing['size']} в чате по силе"
    return card


def player_caption(s) -> str:
    """Подпись под карточкой игрока одной строкой: ник, ранг и ≈MMR с дельтой — остальное на карточке."""
    head = f"🪪 <b>{_esc(s.display_name)}</b> · {html.escape(s.rank)}"
    if s.current_mmr is not None:
        head += f" · ≈{s.current_mmr}"
        if s.games_total and s.anchor_games and s.mmr_delta:
            head += f" ({signed(s.mmr_delta)})"
    return head


# --- герои, позиции, герой и пати --------------------------------------------------------------------

def hero_rows(rows: list[dict]) -> list[dict]:
    """Строки `stats.hero_stats` → строки таблицы героев (имя героя, IMP/GPM под короткими ключами)."""
    return [{"hero_id": r["hero_id"], "name": hero_name(r["hero_id"]), "games": r["games"], "wins": r["wins"],
             "losses": r["losses"], "winrate": r["winrate"], "kda": r["kda"], "imp": r.get("avg_imp"),
             "gpm": r.get("avg_gpm")} for r in rows]


def role_rows(rows: list[dict]) -> list[dict]:
    """Строки `stats.role_stats` → позиции с короткой подписью («Керри», без «Pos 1 ·»)."""
    out = []
    for r in rows:
        full = POSITION_NAMES.get(r["position"], f"Pos {r['position']}")
        out.append({"position": r["position"], "label": full.split("·")[-1].strip(), "games": r["games"],
                    "wins": r["wins"], "losses": r["losses"], "winrate": r["winrate"], "kda": r["kda"]})
    return out


def party_hero_rows(summaries: list) -> list[dict]:
    """Любимые герои пати: по игроку — аватар и топ-3 героя."""
    return [{"name": s.display_name, "avatar": s.avatar,
             "heroes": [{"hero_id": h["hero_id"], "name": hero_name(h["hero_id"]), "games": h["games"],
                         "winrate": h["winrate"]} for h in (s.top_heroes or [])[:3]]} for s in summaries]


def hero_detail_rows(entries: list, avatars_by_account: Optional[dict] = None) -> list[dict]:
    """Кто из пати играл на герое: [(игрок, статистика)] → строки с аватаром игрока."""
    avatars_by_account = avatars_by_account or {}
    out = []
    for player, s in entries:
        out.append({"name": player.display_name, "avatar": avatars_by_account.get(player.account_id) or getattr(player, "steam_avatar", None),
                    "games": s["games"], "wins": s["wins"], "losses": s["losses"], "winrate": s["winrate"],
                    "kda": s["kda"], "imp": s.get("avg_imp"), "gpm": s.get("avg_gpm")})
    return out


def heroes_caption(name: str, period: str, rows: list[dict], roles: Optional[list[dict]] = None) -> str:
    """Подпись под картинкой «Герои игрока»: сколько героев и лучший по играм."""
    head = f"🦸 <b>Герои: {_esc(name)}</b> · <i>{PERIOD_LABELS.get(period, '')}</i>"
    if not rows:
        return head + " · игр нет"
    top = rows[0]
    return head + f"\n{len(rows)} {plural_heroes(len(rows))} · чаще всего <b>{_esc(top['name'])}</b> ({plural_games(top['games'])})"


def roles_caption(name: str, period: str, roles: list[dict]) -> str:
    head = f"🧭 <b>Позиции: {_esc(name)}</b> · <i>{PERIOD_LABELS.get(period, '')}</i>"
    if not roles:
        return head + " · данных нет"
    top = max(roles, key=lambda r: r["games"])
    return head + f"\nчаще всего P{top['position']} {_esc(top['label'])} ({plural_games(top['games'])})"


def hero_caption(hero: str, period: str, entries: list) -> str:
    head = f"🦸 <b>Герой: {_esc(hero)}</b> · <i>{PERIOD_LABELS.get(period, '')}</i>"
    if not entries:
        return head + " · никто из пати не играл"
    player, s = entries[0]
    return head + f"\nчаще всех: <b>{_esc(player.display_name)}</b> ({plural_games(s['games'])}, {round(s['winrate'] * 100)}%)"


# --- рекорды -----------------------------------------------------------------------------------------

def record_tiles(data: dict, tz: str = "UTC") -> list[dict]:
    """Рекорды периода (`records.compute_records`) → плитки: показатель, значение, игрок, герой, дата матча."""
    return [{"label": r["title"], "value": r["text"], "player": r["player"], "hero_id": r["match"].get("hero_id"),
             "date": fmt_local(r["match"]["start_time"], tz, "%d.%m.%y"), "anti": bool(r.get("anti"))}
            for r in data.get("records") or []]


def records_caption(data: dict, period: str) -> str:
    head = f"🌟 <b>Рекорды пати</b> · <i>{PERIOD_LABELS.get(period, '')}</i>"
    records = data.get("records") or []
    if not records:
        return head + " · данных нет"
    best = next((r for r in records if r["key"] == "kills"), records[0])
    return head + f"\n{len(records)} рекордов · {best['title'].lower()}: <b>{_esc(best['player'])}</b> — {_esc(best['text'])}"


# --- недельная сводка ----------------------------------------------------------------------------------

WEEKLY_DUPLICATES = {"climb", "drop", "games", "win_streak"}  # эти итоги уже есть в плитках шапки


def weekly_tiles(report: dict) -> list[dict]:
    """Плитки сводки недели: всего игр, чемпион (или кто играл больше всех), лучшая серия и игры вместе."""
    rows = [r for r in report["rows"] if r["games"] > 0]
    if not rows:
        return []
    games = sum(r["games"] for r in rows)
    wins = sum(r["wins"] for r in rows)
    delta = sum(r["delta"] for r in rows)
    tiles = [{"label": "Всего за неделю", "value": plural_games(games), "sub": f"{_wr(games, wins)} · {signed(delta)}",
              "color": delta_color(delta)}]
    champion = report.get("champion")
    if champion:  # чемпион недели по общему зачёту соревнования занимает место «больше всех играл»
        tiles.append({"label": "Чемпион недели", "value": clean(champion["player"]),
                      "sub": f"{champion['points']} очк. в соревновании", "color": GOLD})
    else:
        busiest = max(rows, key=lambda r: r["games"])
        tiles.append({"label": "Больше всех играл", "value": clean(busiest["name"]),
                      "sub": plural_games(busiest["games"]), "color": None})
    if report.get("streak"):
        name, length = report["streak"]
        tiles.append({"label": "Лучшая серия побед", "value": f"{length} подряд", "sub": clean(name), "color": GOLD})
    if (report.get("shared") or {}).get("games"):
        shared = report["shared"]
        tiles.append({"label": "Вместе", "value": plural_games(shared["games"]),
                      "sub": f"{shared['wins']}–{shared['losses']}", "color": None})
    return tiles[:4]


def weekly_records(report: dict) -> list[dict]:
    """«Герой недели» плиткой с иконкой героя."""
    hero = report.get("hero")
    if not hero:
        return []
    return [{"label": "Герой недели", "value": hero_name(hero["hero_id"]),
             "player": f"{plural_games(hero['games'])} · {round(hero['wins'] * 100 / hero['games'])}%",
             "hero_id": hero["hero_id"]}]


def weekly_awards(report: dict) -> list[dict]:
    return award_items([a for a in report.get("awards") or [] if a["key"] not in WEEKLY_DUPLICATES])


def weekly_caption(report: dict) -> str:
    rows = [r for r in report["rows"] if r["games"] > 0]
    head = "📅 <b>Итоги недели</b>"
    if not rows:
        return head + " · ранкед-игр не было"
    games = sum(r["games"] for r in rows)
    best = max(rows, key=lambda r: r["delta"])
    lead = f" · Лидер: <b>{_esc(best['name'])}</b> {signed(best['delta'])}" if best["delta"] > 0 and len(rows) >= 2 else ""
    return f"{head} · {plural_games(games)}{lead}"


# --- ежедневная сводка: скользящие 24 часа ---------------------------------------------------------------

DAILY_TICK_HOURS = 3  # подписи оси таймлайна — каждые 3 часа по часам чата


def _daily_rank_text(meta: dict) -> str:
    """«Legend 5 · ≈5420» — ранг и оценка MMR под ником (что известно)."""
    parts = [clean(meta["rank_text"])] if meta.get("rank_text") else []
    if meta.get("mmr") is not None:
        parts.append(f"≈{meta['mmr']}")
    return " · ".join(parts)


def daily_rows(report: dict, info: dict) -> list[dict]:
    """Строки таблицы суток: крупно ±MMR за 24 часа, под ним игры и KDA, динамика дня, любимый герой дня.

    Игравшие идут первыми (как их отсортировал отчёт), не игравшие — в конце коротким «не играл».
    """
    rows = []
    for r in report["rows"]:
        meta = info.get(r["name"]) or {}
        row = {"name": r["name"], "avatar": meta.get("avatar"), "rank_tier": meta.get("rank_tier"),
               "rank_text": _daily_rank_text(meta), "games": r["games"], "wins": r["wins"], "losses": r["losses"]}
        if r["games"]:
            top = r.get("hero")
            row.update(big=signed(r["delta"]), big_color=delta_color(r["delta"]),
                       sub=f"{plural_games(r['games'])} · KDA {r['kda']:.2f}",
                       series=[0] + list(r["series"]),  # день начинается с нуля: линия растёт/падает от стартовой точки
                       hero_id=top["hero_id"] if top else None, hero_note=f"×{top['games']}" if top else "")
        else:
            row.update(big="0", big_color=MUTED, sub="не играл", series=[], hero_id=None, hero_note="")
        rows.append(row)
    return rows


def _daily_ticks(since: int, until: int, tz_name: str) -> list[tuple[int, str]]:
    """Подписи оси времени: круглые часы чата, кратные DAILY_TICK_HOURS, внутри окна → [(время, «15:00»)]."""
    ticks = []
    ts = -(-since // 900) * 900  # шаг 15 минут: подходит и поясам со сдвигом в полчаса
    while ts <= until:
        local = local_time(ts, tz_name)
        if local.minute == 0 and local.hour % DAILY_TICK_HOURS == 0:
            ticks.append((ts, f"{local:%H:%M}"))
        ts += 900
    return ticks


def _daily_tiles(report: dict) -> list[dict]:
    """Плитки сводки суток: игры, лидер, лучшая серия и игры вместе."""
    totals = report["totals"]
    games = totals["games"]
    if not games:
        return []
    tiles = [{"label": "Игр за 24 часа", "value": plural_games(games),
              "sub": f"{_wr(games, totals['wins'])} · {signed(totals['delta'])}", "color": delta_color(totals["delta"])}]
    played = [r for r in report["rows"] if r["games"]]
    best = max(played, key=lambda r: (r["delta"], r["wins"]))
    if len(played) >= 2 and best["delta"] > 0:
        tiles.append({"label": "Лидер суток", "value": clean(best["name"]),
                      "sub": f"{signed(best['delta'])} ({best['wins']}–{best['losses']})", "color": GOLD})
    if report.get("streak"):
        name, length = report["streak"]
        tiles.append({"label": "Лучшая серия побед", "value": f"{length} подряд", "sub": clean(name), "color": GOLD})
    if (report.get("shared") or {}).get("games"):
        shared = report["shared"]
        tiles.append({"label": "Вместе", "value": plural_games(shared["games"]),
                      "sub": f"{shared['wins']}–{shared['losses']}", "color": None})
    return tiles[:4]


def _daily_records(report: dict) -> list[dict]:
    """«Герой суток» плиткой с иконкой, затем рекорды суток (до шести плиток всего)."""
    items = []
    hero = report.get("hero")
    if hero:
        items.append({"label": "Герой суток", "value": hero_name(hero["hero_id"]),
                      "player": f"{plural_games(hero['games'])} · {round(hero['wins'] * 100 / hero['games'])}%",
                      "hero_id": hero["hero_id"]})
    for r in daily_record_picks(report.get("records") or [], 6 - len(items)):
        items.append({"label": r["title"], "value": r["text"], "player": r["player"],
                      "hero_id": (r.get("match") or {}).get("hero_id")})
    return items


def _daily_best_game(report: dict) -> Optional[dict]:
    """Лучшая игра суток для карточки: игрок, герой, K/D/A, KDA, плитки показателей и билд (если известен)."""
    best = report.get("best_game")
    if not best:
        return None
    match = best["match"]
    return {
        "player": clean(best["player"]), "hero_id": match.get("hero_id"), "match_id": match.get("match_id"),
        "won": bool(best.get("won")), "start_time": match.get("start_time"),
        "kills": best["kills"], "deaths": best["deaths"], "assists": best["assists"], "kda": f"{best['kda']:.1f}",
        "stats": [{"label": label, "value": value} for label, value in best_game_stats(match)],
        "build": best.get("build"),
    }


def daily_card(report: dict, info: Optional[dict] = None) -> dict:
    """Отчёт суток → описание карточки для daily_image.render_daily_image.

    info — {ник: {avatar, rank_tier, rank_text, mmr}}: то, чего нет в отчёте (аватар, значок ранга, оценка MMR).
    """
    info = info or {}
    totals = report["totals"]
    games = totals["games"]
    tz = report.get("tz", "UTC")
    rows = daily_rows(report, info)
    lanes = [{"name": r["name"], "avatar": (info.get(r["name"]) or {}).get("avatar"), "games": list(r["timeline"])}
             for r in report["rows"] if r["games"]]
    if games:  # когда играли — видно по таймлайну ниже, строкой не дублируем
        span, sub = None, f"{plural_games(games)} · {_wr(games, totals['wins'])}"
    else:
        span, sub = "За эти сутки ранкед-игр не было", "игр не было"
    return {
        "title": "Ежедневная сводка",
        "window": f"Последние 24 часа · {fmt_window(report)}",
        "span": span,
        "badge": ("24 ЧАСА", ACCENT),
        "big": {"value": signed(totals["delta"]), "color": delta_color(totals["delta"]),
                "label": "оценка ±MMR пати за 24 часа", "sub": sub},
        "tiles": _daily_tiles(report),
        "rows": rows,
        "timeline": {"since": report["since"], "until": report["until"], "tz": tz, "lanes": lanes,
                     "ticks": _daily_ticks(report["since"], report["until"], tz)},
        "records": _daily_records(report),
        "best_game": _daily_best_game(report),
        "footer": f"Оценка MMR: ±{report.get('step', 25)} за игру · учтены игры за последние 24 часа до отправки",
        "note": None,
    }


def daily_caption(report: dict) -> str:
    """Подпись под картинкой сводки: игры за 24 часа и лидер суток."""
    head = "📰 <b>Ежедневная сводка</b>"
    totals = report.get("totals") or {}
    if not totals.get("games"):
        return head + " · за 24 часа ранкед-игр не было"
    caption = f"{head} · 24 ч · {plural_games(totals['games'])} · {_wr(totals['games'], totals['wins'])}"
    played = [r for r in report["rows"] if r["games"]]
    best = max(played, key=lambda r: (r["delta"], r["wins"]))
    if len(played) >= 2 and best["delta"] > 0:
        caption += f"\n🚀 Лидер суток: <b>{_esc(best['name'])}</b> {signed(best['delta'])} ({best['wins']}–{best['losses']})"
    return caption


# --- сравнение и совместные игры -------------------------------------------------------------------------

def compare_rows(comparison: dict, summaries: list) -> list[dict]:
    """Строки сравнения по убыванию «силы в чате»: индекс и четыре показателя с местом среди участников."""
    order = sorted(summaries, key=lambda s: comparison["players"][s.display_name]["power_rank"])
    rows = []
    for s in order:
        info = comparison["players"][s.display_name]
        ranks = info["ranks"]
        power = info["power"]
        perf = f"{s.avg_perf * 100:.0f}" if s.avg_perf is not None else None
        winrate = f"{s.winrate * 100:.0f}%" if s.games_total else None
        kda = f"{s.kda_ratio:.1f}" if s.games_total else None
        gpm = f"{s.avg_gpm_window:.0f}" if s.avg_gpm_window is not None else None
        rows.append({
            "name": s.display_name, "avatar": s.avatar, "rank_tier": s.rank_tier, "rank_text": s.rank, "power": power,
            "index_text": f"{power * 100:.0f}" if power is not None else None,
            "cells": [{"value": value, "rank": ranks.get(key)} for key, value in
                      (("perf", perf), ("winrate", winrate), ("kda", kda), ("gpm", gpm))],
        })
    return rows


def compare_caption(comparison: dict, summaries: list) -> str:
    head = f"⚖️ <b>Сравнение игроков</b> · участников: {comparison['size']}"
    top = [s for s in summaries if comparison["players"][s.display_name]["power_rank"] == 1]
    if len(summaries) < 2 or not top or comparison["players"][top[0].display_name]["power"] is None:
        return head
    power = comparison["players"][top[0].display_name]["power"]
    return head + f"\nсильнее всех в чате: <b>{_esc(top[0].display_name)}</b> · индекс {power * 100:.0f}"


def together_card(result: dict) -> tuple[dict, Optional[dict], list, list]:
    """Результат `build_together` → (сводка, лучшая пара для карточки, игроки, пары)."""
    duo = result.get("duo")
    card_duo = {"names": duo["pair"], "games": duo["games"], "wins": duo["wins"]} if duo else None
    return result.get("summary") or {}, card_duo, result.get("players") or [], result.get("pairs") or []


def together_caption(result: dict) -> str:
    summary = result.get("summary") or {}
    games = summary.get("games", 0)
    head = "🤝 <b>Совместные игры</b>"
    if not games:
        return head + " · совместных игр пока нет"
    wins = summary.get("wins", 0)
    caption = head + f" · {plural_games(games)} · {wins}–{summary.get('losses', 0)} ({round(wins * 100 / games)}%)"
    duo = result.get("duo")
    if duo:
        caption += f"\nлучшая пара: <b>{_esc(duo['pair'][0])} + {_esc(duo['pair'][1])}</b> — {plural_games(duo['games'])}"
    return caption


# --- соревнование чата -------------------------------------------------------------------------------

def contest_view(standings: list, points: list, avatars: dict) -> tuple[list[dict], list[dict]]:
    """Данные карточки соревнования: (общий зачёт, номинации). avatars — {ник: ссылка на аватар}."""
    table = [{"name": p["player"], "avatar": avatars.get(p["player"]), "points": p["points"], "golds": p["golds"]}
             for p in points]
    noms = [{"title": s["title"], "anti": s["anti"], "entries": [
        {"name": e["player"], "avatar": avatars.get(e["player"]), "place": e["place"], "text": e["text"]}
        for e in s["entries"]]} for s in standings]
    return table, noms


def contest_caption(period: str, table: list[dict], noms: list[dict]) -> str:
    """Короткая подпись к фото: период, лидер общего зачёта и число номинаций."""
    head = f"🏅 <b>Соревнование {html.escape(period.lower())}</b>"
    if not table:
        return head + " · пока не с кем соревноваться"
    lead = table[0]
    line = f"{head}\nлидер: <b>{_esc(lead['name'])}</b> — {lead['points']} очк."
    if len(table) > 1:
        line += f" · дальше {_esc(table[1]['name'])} ({table[1]['points']})"
    good = sum(1 for n in noms if not n["anti"])
    return line + f"\nноминаций: {good}" + (f" и антирекордов: {len(noms) - good}" if len(noms) > good else "")


# --- карточка любого игрока по ID (поиск) ----------------------------------------------------------

LOOKUP_GAMES = 100  # сколько последних ранкед-игр берём у OpenDota для карточки игрока не из пати


def lookup_matches(matches: list, recent: Optional[list] = None) -> list[dict]:
    """Ранкед-матчи OpenDota (/matches) + подробности из /recentMatches (GPM, урон) → по возрастанию времени."""
    from mmrbot.stats import is_ranked_lobby
    details = {r.get("match_id"): r for r in recent or [] if isinstance(r, dict)}
    rows = []
    for raw in matches or []:
        if not isinstance(raw, dict) or raw.get("start_time") is None or raw.get("player_slot") is None \
                or raw.get("radiant_win") is None:
            continue
        if raw.get("lobby_type") is not None and not is_ranked_lobby(raw["lobby_type"]):
            continue
        extra = details.get(raw.get("match_id")) or {}
        rows.append({
            "match_id": raw.get("match_id"), "start_time": raw["start_time"], "player_slot": raw["player_slot"],
            "radiant_win": raw["radiant_win"], "hero_id": raw.get("hero_id"), "kills": raw.get("kills") or 0,
            "deaths": raw.get("deaths") or 0, "assists": raw.get("assists") or 0, "duration": raw.get("duration"),
            "party_size": raw.get("party_size"), "average_rank": raw.get("average_rank"),
            "gpm": extra.get("gold_per_min"), "hero_damage": extra.get("hero_damage"),
        })
    return sorted(rows, key=lambda m: m["start_time"])


def lookup_card(account_id: int, profile: dict, matches: list[dict], tz: str = "UTC",
                tracked_name: Optional[str] = None) -> dict:
    """Карточка игрока, которого нет в пати (поиск по ID): профиль OpenDota и его последние ранкед-игры.

    matches — из lookup_matches. Оценки MMR тут нет (её ведёт только пати), поэтому справа крупно — винрейт,
    а линия — баланс побед и поражений по играм. Ключи — как у player_card.
    """
    import statistics

    from mmrbot import stats
    from mmrbot.ranks import rank_label

    profile = profile or {}
    name = clean(profile.get("personaname")) or f"Игрок {account_id}"
    agg = stats.aggregate(matches)
    games = agg.games
    subtitle = f"ID {account_id}" + (f"  ·  в пати: {clean(tracked_name)}" if tracked_name else "  ·  не в пати")
    card: dict = {
        "name": name, "subtitle": subtitle, "avatar": profile.get("avatarfull"), "rank_tier": profile.get("rank_tier"),
        "rank_text": rank_label(profile.get("rank_tier"), profile.get("leaderboard_rank")),
        "mmr_text": f"{agg.winrate * 100:.0f}%" if games else "—",
        "headline_note": f"винрейт за {plural_games(games)}" if games else "ранкед-игр не видно",
        "mmr_delta": None, "perf": None, "warnings": [], "note": "OpenDota · последние ранкед-игры, без оценки MMR",
    }
    streak_type, streak_len = stats.current_streak(matches)
    card["streak"] = (streak_type, streak_len) if streak_len >= 2 else None
    if not games:
        card["warnings"].append("Ранкед-игр не видно: профиль закрыт или в Dota 2 выключены публичные данные матчей.")
        return card

    def mean(key: str) -> tuple[Optional[float], int]:
        values = [m[key] for m in matches if m.get(key) is not None]
        return (sum(values) / len(values) if values else None), len(values)

    gpm, gpm_n = mean("gpm")
    damage, damage_n = mean("hero_damage")
    pool = stats.hero_pool(matches)
    card["tiles"] = [
        {"label": "Результат", "value": f"{agg.wins}–{agg.losses}", "sub": f"{agg.winrate * 100:.0f}% винрейт",
         "color": delta_color((agg.winrate - 0.5) * 100)},
        {"label": "KDA", "value": f"{agg.kda_ratio:.2f}", "sub": f"{agg.avg_kills:.0f}/{agg.avg_deaths:.0f}/{agg.avg_assists:.0f}"},
        {"label": "GPM", "value": f"{gpm:.0f}" if gpm is not None else "—",
         "sub": f"по {plural_games(gpm_n)}" if gpm_n else None},
        {"label": "Урон по героям", "value": _k(damage), "sub": f"по {plural_games(damage_n)}" if damage_n else None},
        {"label": "Пул героев", "value": str(pool), "sub": f"{plural_heroes(pool)} за {plural_games(games)}"},
    ]
    balance, series = 0, []
    for m in matches[-60:]:
        balance += 1 if stats.is_win(m["player_slot"], m["radiant_win"]) else -1
        series.append(balance)
    if len(series) >= 2:
        card["series"] = series
        card["series_label"] = f"Победы минус поражения · последние {plural_games(len(series))}"
    card["form"] = stats.recent_form(matches, 10)
    split = stats.solo_party_split(matches)
    card["split"] = [{"label": label, "wins": split[key][1], "losses": split[key][0] - split[key][1]}
                     for label, key in (("Соло", "solo"), ("В группе", "party")) if split[key][0]]
    facts = []
    best = stats.longest_win_streak(matches)
    if best >= 2:
        facts.append(("Лучшая серия", plural_wins(best), WIN))
    duration = stats.duration_stats(matches)["avg_minutes"]
    if duration:
        facts.append(("Средняя игра", f"{duration:.0f} мин", None))
    card["facts"] = facts
    card["heroes"] = [{"hero_id": h["hero_id"], "name": hero_name(h["hero_id"]), "games": h["games"], "wins": h["wins"],
                       "winrate": h["winrate"], "kda": h.get("kda")} for h in stats.top_heroes(matches, 3)]
    last = stats.last_game(matches)
    if last:
        card["last_game"] = {"hero_id": last["hero_id"], "name": hero_name(last["hero_id"]), "kills": last["kills"],
                             "deaths": last["deaths"], "assists": last["assists"], "kda": last["kda"], "won": last["won"],
                             "when": fmt_local(last["start_time"], tz, "%d.%m %H:%M") if last.get("start_time") else None,
                             "stats": _last_game_stats(last)}
    card["recent"] = recent_items(stats.recent_games(matches, 0), tz)
    card["recent_mmr"] = False
    lobby = [m["average_rank"] for m in matches if m.get("average_rank")]
    if lobby:
        card["lobby_rank"] = statistics.median_low(lobby)
        card["lobby_text"] = rank_label(card["lobby_rank"])
    return card


def lookup_text(card: dict) -> str:
    """Та же карточка игрока по ID текстом (для «📝 Текстом» и чатов с отчётами текстом)."""
    lines = [f"🔎 <b>{_esc(card['name'])}</b> · {html.escape(clean(card.get('rank_text')) or 'Без ранга')}",
             f"<i>{html.escape(clean(card.get('subtitle')))}</i>"]
    tiles = {t["label"]: t for t in card.get("tiles") or []}
    if tiles:
        result, kda = tiles["Результат"], tiles["KDA"]
        lines.append(f"📊 {result['value']} ({result['sub']}) · KDA {kda['value']} ({kda['sub']})")
        econ = [f"{label} {tiles[label]['value']}" for label in ("GPM", "Урон по героям") if tiles[label]["value"] != "—"]
        if econ:
            lines.append("💰 " + " · ".join(econ))
    if card.get("heroes"):
        heroes = ", ".join(f"{_esc(h['name'])} {h['wins']}–{h['games'] - h['wins']}" for h in card["heroes"])
        lines.append(f"🦸 {heroes}")
    if card.get("recent"):
        lines.append("🕘 " + " ".join(("🟢" if g["won"] else "🔴") for g in card["recent"]) + " — последние, новые слева")
    if card.get("lobby_text"):
        lines.append(f"🏟️ Средний уровень лобби: {html.escape(card['lobby_text'])}")
    lines += [f"⚠️ {html.escape(w)}" for w in card.get("warnings") or []]
    if card.get("note"):
        lines.append(f"<i>{html.escape(card['note'])}</i>")
    return "\n".join(lines)


def lookup_caption(card: dict) -> str:
    """Подпись под картинкой карточки по ID: ник и ранг одной строкой."""
    return f"🔎 <b>{_esc(card['name'])}</b> · {html.escape(clean(card.get('rank_text')) or 'Без ранга')}"


# --- матчи игрока страницей ------------------------------------------------------------------------

def match_list_rows(matches: list, offset: int, step: int, tz: str = "UTC", show_delta: bool = True,
                    current: Optional[int] = None) -> list[dict]:
    """Матчи страницы (новые сверху) → строки картинки списка; номер строки (с 1) — подпись кнопки, которая его открывает.

    current — номер открытого сейчас матча на странице (подсвечивается); show_delta — показывать ±MMR (MMR задан).
    """
    from mmrbot.stats import is_win, match_mmr_delta
    rows = []
    for i, m in enumerate(matches, start=1):
        extra = []
        if m.get("position"):
            extra.append(f"P{m['position']}")
        if m.get("gpm"):
            extra.append(f"{round(m['gpm'])} GPM")
        if m.get("last_hits") is not None:
            extra.append(f"{m['last_hits']} крипов")
        rows.append({
            "n": i, "hero_id": m.get("hero_id"), "name": hero_name(m.get("hero_id")),
            "won": is_win(m["player_slot"], m["radiant_win"]), "kills": m.get("kills") or 0,
            "deaths": m.get("deaths") or 0, "assists": m.get("assists") or 0,
            "delta": match_mmr_delta(m, step) if show_delta else None, "double_down": bool(m.get("double_down")),
            "minutes": round(m["duration"] / 60) if m.get("duration") else None,
            "when": fmt_local(m["start_time"], tz, "%d.%m %H:%M") if m.get("start_time") else None,
            "extra": " · ".join(extra) or None, "current": current == i, "level": m.get("level"),
            "plus_xp": m.get("plus_xp"),
        })
    return rows


def match_list_text(name: str, rows: list, offset: int, total: int) -> str:
    """Та же страница текстом: «3. 🏆 Pudge 12/3/8 · +25 · 14.10 21:40» — номер совпадает с кнопкой."""
    if not total:
        return f"📜 <b>{_esc(name)}</b>: ранкед-матчей пока нет."
    lines = [f"📜 <b>Матчи: {_esc(name)}</b> · {offset + 1}–{offset + len(rows)} из {total}",
             "Нажмите номер матча — покажу его картинкой."]
    for r in rows:
        mark = "🏆" if r["won"] else "💀"
        delta = f" · {signed(r['delta'])}" + (" ×2" if r["double_down"] else "") if r.get("delta") is not None else ""
        lines.append(f"{r['n']}. {mark} {html.escape(r['name'])} {r['kills']}/{r['deaths']}/{r['assists']}{delta}"
                     + (f" · {r['when']}" if r.get("when") else ""))
    return "\n".join(lines)
