"""Статистика по героям в матче: против кого пати проигрывает и с кем в команде выигрывает (чистые функции).

Источник — составы команд (storage.get_lineups): герои света и тьмы по каждому матчу. Матчи без известного
состава в расчёт не входят — отчёт говорит, по скольким играм из всех он посчитан.

Порядок в списках — не по «сырому» винрейту: 0 побед из 3 выглядит хуже, чем 7 из 20, хотя знаем мы о нём меньше.
Винрейт сглаживается к общему винрейту игрока (как будто к играм добавили PRIOR «средних»): редкий герой
поднимается в начало списка, только если расхождение действительно большое.
"""
from __future__ import annotations

from typing import Iterable, Optional

from mmrbot.stats import is_win

MIN_GAMES = 3  # меньше встреч — не закономерность
PRIOR = 10.0  # «вес» общего винрейта в сглаживании, в играх
TOP = 5


def _side(match: dict) -> bool:
    return match["player_slot"] < 128


def _tally(bucket: dict, hero_id: int, won: bool) -> None:
    stat = bucket.setdefault(hero_id, [0, 0])
    stat[0] += 1
    stat[1] += 1 if won else 0


def _rows(bucket: dict, base: float, min_games: int) -> list[dict]:
    rows = []
    for hero_id, (games, wins) in bucket.items():
        if games < min_games:
            continue
        rows.append({
            "hero_id": hero_id, "games": games, "wins": wins, "losses": games - wins, "winrate": wins / games,
            "score": (wins + PRIOR * base) / (games + PRIOR),  # сглаженный винрейт — по нему порядок
        })
    return rows


def _split(rows: list[dict], base: float, top: int) -> tuple[list[dict], list[dict]]:
    """(лучшие, худшие) относительно общего винрейта: герой попадает только в один список."""
    best = sorted((r for r in rows if r["score"] > base), key=lambda r: (-r["score"], -r["games"], r["hero_id"]))
    worst = sorted((r for r in rows if r["score"] < base), key=lambda r: (r["score"], -r["games"], r["hero_id"]))
    return best[:top], worst[:top]


def _report(against: dict, allies: dict, counted: int, wins: int, total: int, min_games: int, top: int) -> dict:
    base = wins / counted if counted else 0.5
    easy, hard = _split(_rows(against, base, min_games), base, top)
    good, bad = _split(_rows(allies, base, min_games), base, top)
    return {
        "total": total, "games": counted, "wins": wins, "losses": counted - wins, "winrate": base,
        "hard": hard, "easy": easy, "good_allies": good, "bad_allies": bad, "min_games": min_games,
    }


def player_matchups(
    matches: Iterable[dict], lineups: dict, min_games: int = MIN_GAMES, top: int = TOP,
) -> dict:
    """Герои, против которых и с которыми играл один игрок.

    matches — его матчи (match_id, player_slot, radiant_win, hero_id); lineups — {match_id: (свет, тьма)}.
    → {total, games, wins, losses, winrate, hard, easy, good_allies, bad_allies, min_games}:
      total — всего матчей, games — из них с известным составом; hard/easy — соперники, против которых
      винрейт ниже/выше обычного; good_allies/bad_allies — то же про героев в своей команде (кроме своего).
      Строка списка: {hero_id, games, wins, losses, winrate, score}.
    """
    against: dict = {}
    allies: dict = {}
    total = counted = wins = 0
    for match in matches:
        total += 1
        lineup = lineups.get(match["match_id"])
        if not lineup:
            continue
        radiant = _side(match)
        won = is_win(match["player_slot"], match["radiant_win"])
        counted += 1
        wins += 1 if won else 0
        mine, theirs = (lineup[0], lineup[1]) if radiant else (lineup[1], lineup[0])
        own_hero = match.get("hero_id")
        skipped_own = False
        for hero_id in mine:
            if hero_id == own_hero and not skipped_own:  # свой герой — не «союзник»
                skipped_own = True
                continue
            _tally(allies, hero_id, won)
        for hero_id in theirs:
            _tally(against, hero_id, won)
    return _report(against, allies, counted, wins, total, min_games, top)


def party_matchups(
    named_matches: Iterable[tuple[str, list[dict]]], lineups: dict, min_games: int = MIN_GAMES, top: int = TOP,
) -> dict:
    """То же для всей пати: каждая игра считается один раз, сколько бы игроков чата в ней ни было.

    named_matches — [(имя, матчи игрока)]. Союзники — герои своей команды, на которых играли НЕ игроки чата
    (свои герои — в /heroes). Матч, где игроки чата оказались по разные стороны, считается за каждую сторону.
    """
    sides: dict[tuple[int, bool], dict] = {}
    total_ids: set[int] = set()
    for _name, matches in named_matches:
        for match in matches:
            total_ids.add(match["match_id"])
            key = (match["match_id"], _side(match))
            entry = sides.setdefault(key, {"won": is_win(match["player_slot"], match["radiant_win"]), "own": []})
            if match.get("hero_id"):
                entry["own"].append(match["hero_id"])
    against: dict = {}
    allies: dict = {}
    counted = wins = 0
    for (match_id, radiant), entry in sides.items():
        lineup = lineups.get(match_id)
        if not lineup:
            continue
        counted += 1
        wins += 1 if entry["won"] else 0
        mine, theirs = (lineup[0], lineup[1]) if radiant else (lineup[1], lineup[0])
        own = list(entry["own"])
        for hero_id in mine:
            if hero_id in own:
                own.remove(hero_id)
                continue
            _tally(allies, hero_id, entry["won"])
        for hero_id in theirs:
            _tally(against, hero_id, entry["won"])
    return _report(against, allies, counted, wins, len(total_ids), min_games, top)


def threshold(period: str) -> int:
    """Порог встреч для периода: за короткий срок хватает и двух, за всё время двух мало."""
    return {"day": 2, "week": 2, "month": 3}.get(period, 4)


def is_empty(report: Optional[dict]) -> bool:
    return not report or not any(report.get(key) for key in ("hard", "easy", "good_allies", "bad_allies"))


# --- тексты и данные карточки -----------------------------------------------------------------------

PERIOD_LABELS = {"day": "за сутки", "week": "за неделю", "month": "за месяц", "year": "за год", "all": "за всё время"}
PERIOD_BADGES = {"day": "ЗА СУТКИ", "week": "ЗА НЕДЕЛЮ", "month": "ЗА МЕСЯЦ", "year": "ЗА ГОД", "all": "ВСЁ ВРЕМЯ"}
SECTIONS = (
    ("hard", "😰 Тяжёлые соперники"), ("easy", "😎 Удобные соперники"),
    ("bad_allies", "📉 С ними в команде хуже"), ("good_allies", "📈 С ними в команде лучше"),
)
NO_LINEUPS = (
    "Составы команд по этим играм ещё не загружены — они подтягиваются фоном вместе с историей матчей. "
    "Загляните позже."
)


def _by_games(n: int) -> str:
    """«по 1 игре», «по 21 игре», «по 5 играм» (дательный падеж)."""
    return f"по {n} игре" if n % 10 == 1 and n % 100 != 11 else f"по {n} играм"


def coverage(report: dict) -> str:
    """«по 120 из 150 игр» — сколько игр с известным составом вошло в расчёт."""
    if report["games"] == report["total"]:
        return _by_games(report["games"])
    return f"по {report['games']} из {report['total']} игр"


def render_matchups(who: Optional[str], period: str, report: dict) -> str:
    """Текстовый отчёт (Telegram HTML). who — ник игрока или None для всей пати."""
    import html

    from mmrbot.heroes import hero_name

    subject = html.escape(who) if who else "пати"
    title = f"⚔️ <b>Соперники и союзники: {subject}</b> · <i>{PERIOD_LABELS.get(period, '')}</i>"
    if not report["total"]:
        return title + "\n😴 За указанный период игр нет."
    if not report["games"]:
        return f"{title}\n{NO_LINEUPS}"
    lines = [title, f"<i>{coverage(report)} · обычный винрейт {report['winrate'] * 100:.0f}%</i>"]
    if is_empty(report):
        lines.append(f"\nПока мало повторов: нужен герой, встреченный хотя бы {report['min_games']} раза.")
        return "\n".join(lines)
    for key, heading in SECTIONS:
        rows = report.get(key) or []
        if not rows:
            continue
        lines.append(f"\n<b>{heading}</b>")
        for row in rows:
            lines.append(
                f"• {html.escape(hero_name(row['hero_id']))} — {row['wins']}–{row['losses']} "
                f"({row['winrate'] * 100:.0f}%)"
            )
    lines.append(f"\n<i>Герой — в списке от {report['min_games']} встреч; порядок учитывает число игр.</i>")
    return "\n".join(lines)


def matchups_caption(who: Optional[str], period: str, report: dict) -> str:
    """Подпись к картинке: о ком, период и самый показательный герой с каждой стороны."""
    import html

    from mmrbot.heroes import hero_name

    subject = html.escape(who) if who else "пати"
    head = f"⚔️ <b>Соперники и союзники: {subject}</b> · {PERIOD_LABELS.get(period, '')}"
    parts = []
    if report.get("hard"):
        row = report["hard"][0]
        parts.append(f"тяжелее всего против {html.escape(hero_name(row['hero_id']))} ({row['wins']}–{row['losses']})")
    if report.get("good_allies"):
        row = report["good_allies"][0]
        parts.append(f"лучше всего с {html.escape(hero_name(row['hero_id']))} ({row['wins']}–{row['losses']})")
    return head + ("\n" + " · ".join(parts).capitalize() if parts else "")


def matchups_view(who: Optional[str], period: str, report: dict) -> dict:
    """Отчёт → описание карточки для matchups_image.render_matchups_image."""
    from mmrbot.heroes import hero_name

    view: dict = {
        "title": f"Соперники и союзники · {who}" if who else "Соперники и союзники",
        "subtitle": f"{coverage(report)} · обычный винрейт {report['winrate'] * 100:.0f}%",
        "badge": PERIOD_BADGES.get(period, ""),
        "footer": f"герой в списке от {report['min_games']} встреч · порядок учитывает число игр",
    }
    for key, _ in SECTIONS:
        view[key] = [dict(row, name=hero_name(row["hero_id"])) for row in report.get(key) or []]
    return view


def hero_ids(view: dict) -> list[int]:
    return [row["hero_id"] for key, _ in SECTIONS for row in view.get(key) or []]
