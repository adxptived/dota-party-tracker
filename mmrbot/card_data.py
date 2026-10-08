"""Данные доменных сводок → описания строк, плиток и подписей для карточек-картинок (чистые функции).

Рисуют карточки stats_image.py и др.; здесь — только «что показать»: текст, цвета, порядок. Сети и БД нет.
"""
from __future__ import annotations

import html
from typing import Optional

from mmrbot.cards import GOLD, MUTED, clean, delta_color, signed
from mmrbot.formatting import PERIOD_LABELS, fmt_local, POSITION_NAMES, PULSE_RECORDS, plural_games, plural_heroes
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
    """Подпись под рейтингом: «🏆 Рейтинг · Лидер: Вася ≈5420 (+75 за неделю)»; для «Сегодня» и сводки дня — лидер дня."""
    if mode in ("today", "digest"):
        played = [s for s in summaries if s.games_today]
        head = "📅 <b>Статистика за сегодня</b>" if mode == "today" else "📰 <b>Ежедневная сводка</b>"
        if not played:
            return head + " · игр пока не было"
        best = max(played, key=lambda s: (s.delta_today, s.wins_today))
        word = "Лидер" if mode == "today" else "Лидер дня"
        return f"{head} · {word}: <b>{_esc(best.display_name)}</b> {signed(best.delta_today)} ({best.wins_today}–{best.losses_today})"
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


# --- карточка игрока ----------------------------------------------------------------------------

def _k(value) -> str:
    if value is None:
        return "—"
    return f"{value / 1000:.1f}k" if value >= 1000 else f"{value:.0f}"


def player_card(s, standing: Optional[dict] = None, series: Optional[list] = None, note: Optional[str] = None) -> dict:
    """Сводка игрока → описание карточки для player_image.render_player_image.

    standing — запись игрока из tracker.build_chat_comparison()["players"][имя] (+ size); series — накопленные ±MMR
    по играм (последние ~60); note — пометка об устаревании данных (обычный текст).
    """
    from mmrbot.formatting import SKILL_GROUPS
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

    partial = f"по {s.detail_games} из {games}" if 0 < s.detail_games < games else None
    card["tiles"] = [
        {"label": "Результат", "value": f"{s.wins_total}–{s.losses_total}", "sub": f"{s.winrate * 100:.0f}% винрейт",
         "color": delta_color((s.winrate - 0.5) * 100)},
        {"label": "KDA", "value": f"{s.kda_ratio:.2f}", "sub": f"{s.avg_kills:.0f}/{s.avg_deaths:.0f}/{s.avg_assists:.0f}"},
        {"label": "GPM", "value": f"{s.avg_gpm_window:.0f}" if s.avg_gpm_window is not None else "—", "sub": partial},
        {"label": "Нетворт", "value": _k(s.avg_net_worth_window), "sub": partial},
        {"label": "Урон по героям", "value": _k(s.avg_hero_damage_window), "sub": partial},
        {"label": "Игр сыграно", "value": str(games), "sub": f"ср. {s.avg_duration_min:.0f} мин" if s.avg_duration_min else None},
    ]
    values = list(series or [])
    if values:
        base = s.anchor_mmr or 0
        card["series"] = [base + v for v in values] if s.anchor_mmr is not None else values
        card["series_label"] = f"Динамика ≈MMR · последние {plural_games(len(values))}" if s.anchor_mmr is not None \
            else f"Динамика ±MMR · последние {plural_games(len(values))}"
    card["form"] = list(s.form_long or [])
    card["split"] = [{"label": label, "wins": pair[1], "losses": pair[0] - pair[1]}
                     for label, pair in (("Соло", s.solo), ("В группе", s.party)) if pair[0]]
    if s.best_hour and s.worst_hour:
        card["hours"] = {"best": f"{s.best_hour[0]:02d}:00 · {s.best_hour[1] * 100:.0f}%",
                         "worst": f"{s.worst_hour[0]:02d}:00 · {s.worst_hour[1] * 100:.0f}%"}
    from mmrbot.heroes import hero_name
    card["heroes"] = [{"hero_id": h["hero_id"], "name": hero_name(h["hero_id"]), "games": h["games"], "wins": h["wins"],
                       "winrate": h["winrate"]} for h in s.top_heroes]
    if s.best_game:
        bg = s.best_game
        card["best_game"] = {"hero_id": bg["hero_id"], "name": hero_name(bg["hero_id"]), "kills": bg["kills"],
                             "deaths": bg["deaths"], "assists": bg["assists"], "kda": bg["kda"]}
    skills = []
    for label, metrics in SKILL_GROUPS:
        pcts = [s.skill[m] for m in metrics if m in (s.skill or {})]
        if pcts:
            skills.append({"label": label, "pct": sum(pcts) / len(pcts)})
    card["skills"] = skills
    if s.lobby_rank:
        card["lobby_rank"], card["lobby_text"] = s.lobby_rank, rank_label(s.lobby_rank)
    if standing and standing.get("size", 0) >= 2 and standing.get("power_rank"):
        card["standing"] = f"#{standing['power_rank']} из {standing['size']} в чате по силе"
    return card


def player_caption(s) -> str:
    """Подпись под карточкой игрока: ник, ранг, ≈MMR с дельтой и результат."""
    head = f"🪪 <b>{_esc(s.display_name)}</b> · {html.escape(s.rank)}"
    if s.current_mmr is not None:
        head += f" · ≈{s.current_mmr}"
        if s.games_total and s.anchor_games and s.mmr_delta:
            head += f" ({signed(s.mmr_delta)})"
    if s.games_total:
        head += f"\n🎮 {plural_games(s.games_total)} · {s.wins_total}–{s.losses_total} ({s.winrate * 100:.0f}%) · KDA {s.kda_ratio:.2f}"
    else:
        head += "\n💤 ранкед-игр пока нет"
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
    """Плитки сводки недели: всего игр, кто поднялся, кто играл больше всех, серия (или игры вместе)."""
    rows = [r for r in report["rows"] if r["games"] > 0]
    if not rows:
        return []
    games = sum(r["games"] for r in rows)
    wins = sum(r["wins"] for r in rows)
    delta = sum(r["delta"] for r in rows)
    tiles = [{"label": "Всего за неделю", "value": plural_games(games), "sub": f"{_wr(games, wins)} · {signed(delta)}",
              "color": delta_color(delta)}]
    best = max(rows, key=lambda r: r["delta"])
    if best["delta"] > 0:
        tiles.append({"label": "Больше всех поднялся", "value": clean(best["name"]),
                      "sub": f"{signed(best['delta'])} ({best['wins']}–{best['losses']})", "color": GOLD})
    busiest = max(rows, key=lambda r: r["games"])
    tiles.append({"label": "Больше всех играл", "value": clean(busiest["name"]), "sub": plural_games(busiest["games"]),
                  "color": None})
    if report.get("streak"):
        name, length = report["streak"]
        tiles.append({"label": "Лучшая серия побед", "value": f"{length} подряд", "sub": clean(name), "color": GOLD})
    elif (report.get("shared") or {}).get("games"):
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


# --- достижения ----------------------------------------------------------------------------------------

def achievements_players(rows: list, avatars: dict, tz: str = "UTC") -> list[dict]:
    """Игроки для карточки достижений: rows [(имя, {code: (ts, деталь)})], avatars {имя: аватар}.

    Неизвестные коды (убранные из каталога) отбрасываются; порядок — по числу значков, затем по имени.
    """
    from mmrbot.achievements import CATALOG
    players = []
    for name, earned in rows:
        items = [{"code": code, "detail": detail, "date": fmt_local(ts, tz, "%d.%m.%Y")}
                 for code, (ts, detail) in sorted(earned.items(), key=lambda kv: kv[1][0]) if code in CATALOG]
        players.append({"name": name, "avatar": avatars.get(name), "items": items})
    players.sort(key=lambda p: (-len(p["items"]), p["name"].lower()))
    return players


def achievements_caption(players: list[dict]) -> str:
    """Короткая подпись к фото: сколько значков у пати и кто впереди."""
    from mmrbot.achievements import CATALOG
    head = "🏅 <b>Достижения</b>"
    counts = [(p["name"], sum(1 for i in p["items"] if not CATALOG[i["code"]].anti),
               sum(1 for i in p["items"] if CATALOG[i["code"]].anti)) for p in players]
    good = sum(c[1] for c in counts)
    anti = sum(c[2] for c in counts)
    if not good and not anti:
        return head + " · пока ни у кого нет"
    line = f"{head}\nвсего {good} достижений"
    if anti:
        line += f" и {anti} антирекордов"
    top = max(counts, key=lambda c: c[1])
    if top[1]:
        line += f" · больше всех у <b>{_esc(top[0])}</b> — {top[1]}"
    return line
