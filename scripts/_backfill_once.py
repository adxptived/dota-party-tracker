"""РАЗОВЫЙ бэкфилл: добить последние 25 ранкед-игр по каждому tracked-аккаунту.

- Тянет последние 25 ранкед-матчей из OpenDota, сохраняет + обогащает (benchmarks → перф/скилл).
- created_ts сдвигается назад, чтобы окно статистики покрыло эти игры.
- anchor (MMR-оценка) НЕ трогается: прошлые игры уже учтены во введённом MMR,
  а текущий тренд с момента добавления сохраняется.
- Ручные фейковые игры (900000001..5) перемещаются в САМЫЕ ДАВНИЕ (не влияют на форму/серию).
Запуск: .venv\\Scripts\\python.exe -m scripts._backfill_once
"""
import json
import sqlite3
import time

from mmrbot import stats
from mmrbot.opendota import OpenDota
from mmrbot.storage import Storage
from mmrbot.tracker import _normalize

DB = "mmrbot.db"
BACKFILL_N = 25
FAKE_LO, FAKE_HI = 900000001, 900000005


def main() -> None:
    st = Storage(DB)
    od = OpenDota(min_interval=1.1)
    now = int(time.time())

    rows = [(c, p) for c in st.list_chats() for p in st.list_players(c.chat_id)]
    print(f"игроков к обработке: {len(rows)}")

    for chat, p in rows:
        acc = p.account_id
        try:
            raw = od.get_matches(acc, limit=200)
        except Exception as exc:
            print(f"  {p.display_name} (chat {chat.chat_id}): матчи не получены ({exc})")
            continue

        ranked = [m for m in raw if stats.is_ranked_lobby(m.get("lobby_type")) and m.get("radiant_win") is not None]
        ranked.sort(key=lambda m: m["start_time"], reverse=True)
        last = ranked[:BACKFILL_N]
        if not last:
            print(f"  {p.display_name} (chat {chat.chat_id}): нет ранкед-игр (приватные данные?) — пропуск")
            continue

        norm = [_normalize(m) for m in last]
        st.add_matches(p.id, norm)

        enriched = 0
        for m in norm:
            try:
                det = od.get_match_player_stats(m["match_id"], acc)
                if det:
                    st.update_match_details(p.id, m["match_id"], det, stats.perf_score(det.get("benchmarks") or {}))
                    enriched += 1
            except Exception:
                pass

        # профиль + карьерные срезы для карточки
        try:
            prof = od.get_profile(acc)
            st.update_player_rank(p.id, prof.get("rank_tier"), prof.get("leaderboard_rank"), now)
            tot = od.get_totals(acc)
            st.update_player_totals(p.id, tot.get("gpm"), tot.get("xpm"), tot.get("last_hits"))
            lanes = od.get_lanes(acc)
            dist = od.get_gpm_distribution(acc)
            st.update_player_insights(p.id, json.dumps({str(k): list(v) for k, v in lanes.items()}),
                                      dist.get("median"), dist.get("best"))
        except Exception:
            pass

        t_min = min(m["start_time"] for m in norm)
        conn = sqlite3.connect(DB)
        fake_ids = [r[0] for r in conn.execute(
            "SELECT match_id FROM matches WHERE player_id=? AND match_id BETWEEN ? AND ? ORDER BY match_id",
            (p.id, FAKE_LO, FAKE_HI)).fetchall()]
        new_created = t_min - 60
        if fake_ids:
            base = t_min - 7 * 86400  # неделя ДО самых старых реальных
            for i, fid in enumerate(fake_ids):
                conn.execute("UPDATE matches SET start_time=? WHERE player_id=? AND match_id=?",
                             (base + i * 3600, p.id, fid))
            new_created = base - 60
        conn.execute("UPDATE players SET created_ts=? WHERE id=?", (new_created, p.id))
        conn.commit()
        conn.close()
        print(f"  {p.display_name} (chat {chat.chat_id}): +{len(norm)} ранкед (обогащено {enriched}), "
              f"фейков в старьё: {len(fake_ids)}")

    print("DONE")


if __name__ == "__main__":
    main()
