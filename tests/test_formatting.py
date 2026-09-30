from mmrbot.formatting import (
    format_delta,
    plural_games,
    render_awards,
    render_compare_table,
    render_heroes,
    render_leaderboard,
    render_player_card,
    render_together,
    standing_line,
)
from mmrbot.tracker import PlayerSummary, build_chat_comparison


def summary(**kw):
    base = dict(
        display_name="Вася",
        account_id=42,
        rank="Divine 5",
        anchor_mmr=5000,
        current_mmr=5050,
        mmr_delta=50,
        games_total=4,
        wins_total=3,
        losses_total=1,
        winrate=0.75,
        kda_ratio=4.2,
        avg_kills=8.0,
        avg_deaths=4.0,
        avg_assists=7.0,
        games_today=2,
        wins_today=2,
        losses_today=0,
        delta_today=50,
    )
    base.update(kw)
    return PlayerSummary(**base)


# --- format_delta -------------------------------------------------------

def test_format_delta_positive():
    assert format_delta(50) == "+50"


def test_format_delta_negative():
    assert format_delta(-100) == "-100"


def test_format_delta_zero():
    assert format_delta(0) == "0"


# --- render_leaderboard -------------------------------------------------

def test_leaderboard_empty_gives_hint():
    text = render_leaderboard([])
    assert "/add" in text


def test_leaderboard_shows_name_rank_mmr_and_estimate_marker():
    text = render_leaderboard([summary()])
    assert "Вася" in text
    assert "Divine 5" in text
    assert "5050" in text
    assert "+50" in text
    assert "≈" in text  # оценка помечена
    assert "75%" in text


def test_leaderboard_orders_and_medals_players():
    text = render_leaderboard([summary(display_name="Aaa"), summary(display_name="Bbb")])
    assert text.index("Aaa") < text.index("Bbb")
    assert "🥇" in text and "🥈" in text


# --- новый дизайн (карточки) --------------------------------------------

def test_plural_games():
    assert plural_games(1) == "1 игра"
    assert plural_games(2) == "2 игры"
    assert plural_games(5) == "5 игр"
    assert plural_games(11) == "11 игр"
    assert plural_games(21) == "21 игра"


def test_zero_games_collapsed_no_noise():
    text = render_leaderboard([summary(games_total=0, wins_total=0, losses_total=0, winrate=0.0, kda_ratio=0.0)])
    assert "пока без игр" in text
    assert "KDA 0.00" not in text
    assert "0–0" not in text


def test_leaderboard_hides_avg_breakdown():
    # Разбивку K/D/A показываем только в /player, не в лидерборде.
    text = render_leaderboard([summary(avg_kills=8.0, avg_deaths=4.0, avg_assists=7.0)])
    assert "8.0/4.0/7.0" not in text


def test_positive_delta_shows_up_arrow():
    text = render_leaderboard([summary(mmr_delta=50, games_total=4)])
    assert "📈" in text


def test_negative_delta_shows_down_arrow():
    text = render_leaderboard([summary(current_mmr=4900, mmr_delta=-100, games_total=4)])
    assert "📉" in text
    assert "-100" in text


def test_name_is_html_escaped_and_bold():
    text = render_leaderboard([summary(display_name="A<b>&")])
    assert "A&lt;b&gt;&amp;" in text  # экранировано
    assert "<b>" in text              # жирный присутствует


def test_leaderboard_negative_delta_shows_minus():
    text = render_leaderboard([summary(current_mmr=4900, mmr_delta=-100)])
    assert "-100" in text
    assert "4900" in text


def test_today_view_marks_no_games():
    text = render_leaderboard([summary(games_today=0, wins_today=0, losses_today=0, delta_today=0)], today_only=True)
    assert "Вася" in text
    # без игр сегодня — не показываем ложную дельту, а пишем про отсутствие игр
    assert "без игр" in text.lower()


def test_player_without_anchor_mmr_shows_question_not_crash():
    text = render_leaderboard([summary(anchor_mmr=None, current_mmr=None, mmr_delta=25)])
    assert "Вася" in text
    assert "+25" in text


def test_leaderboard_shows_win_streak():
    text = render_leaderboard([summary(streak_type="W", streak_len=3)])
    assert "🔥" in text
    assert "3" in text


def test_leaderboard_shows_perf_in_line():
    text = render_leaderboard([summary(avg_perf=0.58, games_total=10)])
    assert "перф 58" in text


# --- awards -------------------------------------------------------------

def test_render_awards_lists_leaders():
    players = [
        summary(display_name="A", winrate=0.8, wins_total=8, losses_total=2, games_total=10, streak_type="W", streak_len=3),
        summary(display_name="B", winrate=0.3, wins_total=3, losses_total=7, games_total=10, streak_type="L", streak_len=4),
    ]
    text = render_awards(players)
    assert "A" in text  # король винрейта / на кураже
    assert "B" in text  # главный тилт (серия поражений)


def test_render_awards_empty_when_no_eligible():
    text = render_awards([summary(games_total=0, wins_total=0, losses_total=0)])
    assert text == ""


# --- together -----------------------------------------------------------

def test_render_together_with_shared_games():
    result = {"player_count": 2, "summary": {"games": 5, "wins": 3, "losses": 2},
              "duo": {"pair": ("Alice", "Bob"), "games": 4, "wins": 3, "winrate": 0.75}}
    text = render_together(result)
    assert "5" in text
    assert "Alice" in text and "Bob" in text


def test_render_together_no_games():
    result = {"player_count": 2, "summary": {"games": 0, "wins": 0, "losses": 0}, "duo": None}
    text = render_together(result)
    assert "нет" in text.lower() or "совмест" in text.lower()


# --- heroes -------------------------------------------------------------

def test_render_heroes_shows_hero_names():
    s = summary(display_name="Вася", top_heroes=[{"hero_id": 1, "games": 5, "wins": 3, "winrate": 0.6}])
    text = render_heroes([s])
    assert "Вася" in text
    assert "Anti-Mage" in text  # hero_id 1


# --- player card --------------------------------------------------------

def test_render_player_card_is_windowed_only():
    # Карточка показывает только окно (последние игры), без карьерных линий/распределений.
    s = summary(
        display_name="Вася",
        avg_gpm_window=520.0, avg_net_worth_window=18000.0, avg_hero_damage_window=22000.0,
        solo=(10, 6), party=(5, 4),
        top_heroes=[{"hero_id": 8, "games": 4, "wins": 3, "winrate": 0.75}],
        lanes={2: (10, 6), 0: (5, 2)},   # карьерное — НЕ должно попасть
        gpm_median=999.0,                # карьерное — НЕ должно попасть
    )
    text = render_player_card(s)
    assert "Вася" in text
    assert "520" in text            # windowed GPM
    assert "Juggernaut" in text     # hero_id 8
    assert "соло" in text.lower()
    assert "Последние" in text      # явная пометка окна
    # карьерных строк быть не должно
    assert "Mid" not in text
    assert "без линии" not in text
    assert "999" not in text


def test_render_player_card_windowed_records():
    s = summary(
        display_name="Вася",
        recent_form=[True, False, True],
        best_game={"kills": 10, "deaths": 1, "assists": 10, "hero_id": 8, "kda": 20.0},
        longest_win_streak=3,
    )
    text = render_player_card(s)
    assert "✅" in text                         # форма
    assert "10/1/10" in text                    # лучшая игра
    assert "3" in text                          # макс серия


def test_render_player_card_shows_perf_score():
    s = summary(avg_perf=0.72, enriched_games=9, avg_hero_damage_window=22000.0, avg_net_worth_window=18000.0)
    text = render_player_card(s)
    assert "72/100" in text
    assert "перф" in text.lower()


def test_render_player_card_shows_skill_breakdown_and_role():
    s = summary(
        role_style="кор (фарм)",
        skill={"gold_per_min": 0.45, "hero_damage_per_min": 0.78, "kills_per_min": 0.66, "hero_healing_per_min": 0.9},
    )
    text = render_player_card(s)
    assert "Скилл" in text
    assert "Фарм" in text            # категория
    assert "78%" in text             # урон-перцентиль
    assert ("▰" in text) or ("▱" in text)  # бар
    assert "стиль" in text.lower() and "кор" in text.lower()


def test_render_player_card_with_standing_block():
    s = summary()
    text = render_player_card(s, standing="📊 В чате (из 3): сила #1 · перф #1")
    assert "В чате" in text
    assert "сила #1" in text


# --- сравнение в чате ---------------------------------------------------

def _two_player_comparison():
    a = summary(display_name="A", avg_perf=0.8, winrate=0.6, kda_ratio=4.0, avg_gpm_window=500.0)
    b = summary(display_name="B", avg_perf=0.4, winrate=0.4, kda_ratio=2.0, avg_gpm_window=400.0)
    return build_chat_comparison([a, b]), [a, b]


def test_render_compare_table_orders_by_power():
    comp, summaries = _two_player_comparison()
    text = render_compare_table(comp, summaries)
    assert "Сила в чате" in text
    assert text.index("A") < text.index("B")   # A первым (сильнее)
    assert "🥇" in text and "🥈" in text


def test_standing_line_shows_ranks():
    comp, _ = _two_player_comparison()
    line = standing_line(comp, "A")
    assert "сила #1" in line
    assert "перф #1" in line


def test_standing_line_none_when_alone():
    a = summary(display_name="Solo", avg_perf=0.5)
    comp = build_chat_comparison([a])
    assert standing_line(comp, "Solo") is None  # сравнивать не с кем
