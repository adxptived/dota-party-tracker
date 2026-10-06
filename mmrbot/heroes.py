"""Справочник героев Dota 2 (id -> имя). Сгенерировано из OpenDota /heroes."""
from __future__ import annotations

HERO_NAMES: dict[int, str] = {
    1: "Anti-Mage",
    2: "Axe",
    3: "Bane",
    4: "Bloodseeker",
    5: "Crystal Maiden",
    6: "Drow Ranger",
    7: "Earthshaker",
    8: "Juggernaut",
    9: "Mirana",
    10: "Morphling",
    11: "Shadow Fiend",
    12: "Phantom Lancer",
    13: "Puck",
    14: "Pudge",
    15: "Razor",
    16: "Sand King",
    17: "Storm Spirit",
    18: "Sven",
    19: "Tiny",
    20: "Vengeful Spirit",
    21: "Windranger",
    22: "Zeus",
    23: "Kunkka",
    25: "Lina",
    26: "Lion",
    27: "Shadow Shaman",
    28: "Slardar",
    29: "Tidehunter",
    30: "Witch Doctor",
    31: "Lich",
    32: "Riki",
    33: "Enigma",
    34: "Tinker",
    35: "Sniper",
    36: "Necrophos",
    37: "Warlock",
    38: "Beastmaster",
    39: "Queen of Pain",
    40: "Venomancer",
    41: "Faceless Void",
    42: "Wraith King",
    43: "Death Prophet",
    44: "Phantom Assassin",
    45: "Pugna",
    46: "Templar Assassin",
    47: "Viper",
    48: "Luna",
    49: "Dragon Knight",
    50: "Dazzle",
    51: "Clockwerk",
    52: "Leshrac",
    53: "Nature's Prophet",
    54: "Lifestealer",
    55: "Dark Seer",
    56: "Clinkz",
    57: "Omniknight",
    58: "Enchantress",
    59: "Huskar",
    60: "Night Stalker",
    61: "Broodmother",
    62: "Bounty Hunter",
    63: "Weaver",
    64: "Jakiro",
    65: "Batrider",
    66: "Chen",
    67: "Spectre",
    68: "Ancient Apparition",
    69: "Doom",
    70: "Ursa",
    71: "Spirit Breaker",
    72: "Gyrocopter",
    73: "Alchemist",
    74: "Invoker",
    75: "Silencer",
    76: "Outworld Destroyer",
    77: "Lycan",
    78: "Brewmaster",
    79: "Shadow Demon",
    80: "Lone Druid",
    81: "Chaos Knight",
    82: "Meepo",
    83: "Treant Protector",
    84: "Ogre Magi",
    85: "Undying",
    86: "Rubick",
    87: "Disruptor",
    88: "Nyx Assassin",
    89: "Naga Siren",
    90: "Keeper of the Light",
    91: "Io",
    92: "Visage",
    93: "Slark",
    94: "Medusa",
    95: "Troll Warlord",
    96: "Centaur Warrunner",
    97: "Magnus",
    98: "Timbersaw",
    99: "Bristleback",
    100: "Tusk",
    101: "Skywrath Mage",
    102: "Abaddon",
    103: "Elder Titan",
    104: "Legion Commander",
    105: "Techies",
    106: "Ember Spirit",
    107: "Earth Spirit",
    108: "Underlord",
    109: "Terrorblade",
    110: "Phoenix",
    111: "Oracle",
    112: "Winter Wyvern",
    113: "Arc Warden",
    114: "Monkey King",
    119: "Dark Willow",
    120: "Pangolier",
    121: "Grimstroke",
    123: "Hoodwink",
    126: "Void Spirit",
    128: "Snapfire",
    129: "Mars",
    131: "Ringmaster",
    135: "Dawnbreaker",
    136: "Marci",
    137: "Primal Beast",
    138: "Muerta",
    145: "Kez",
    155: "Largo",
}




# Русские названия и ходовые прозвища → английское имя (ищем по имени, а не по id: переживает новые id).
_RU_NAMES = {
    "антимаг": "Anti-Mage", "акс": "Axe", "мирана": "Mirana", "джаггернаут": "Juggernaut", "джаггер": "Juggernaut",
    "пудж": "Pudge", "инвокер": "Invoker", "инвок": "Invoker", "зевс": "Zeus", "лина": "Lina", "лион": "Lion",
    "снайпер": "Sniper", "сф": "Shadow Fiend", "шэдоу фиенд": "Shadow Fiend", "шадоу фиенд": "Shadow Fiend",
    "рики": "Riki", "сларк": "Slark", "свен": "Sven", "тини": "Tiny",
    "канкка": "Kunkka", "кункка": "Kunkka", "лич": "Lich", "фантом ассасин": "Phantom Assassin",
    "фантомка": "Phantom Assassin", "па": "Phantom Assassin", "некрофос": "Necrophos", "некр": "Necrophos",
    "тайдхантер": "Tidehunter", "тайд": "Tidehunter", "венга": "Vengeful Spirit", "виндренджер": "Windranger",
    "ренджер": "Windranger", "виндрейнджер": "Windranger", "морф": "Morphling", "морфлинг": "Morphling",
    "рубик": "Rubick", "пак": "Puck", "пуга": "Pugna", "пугна": "Pugna", "дазл": "Dazzle",
    "дэзл": "Dazzle", "бристл": "Bristleback", "бристлбэк": "Bristleback", "спектра": "Spectre",
    "спектр": "Spectre", "медуза": "Medusa", "мипо": "Meepo", "мепо": "Meepo", "энигма": "Enigma",
    "войд": "Faceless Void", "фейслес войд": "Faceless Void", "сайленсер": "Silencer", "варлок": "Warlock",
    "ликан": "Lycan", "луна": "Luna", "омникнайт": "Omniknight", "оракул": "Oracle",
    "тролль": "Troll Warlord", "троль": "Troll Warlord", "урса": "Ursa", "виверн": "Winter Wyvern",
    "тинкер": "Tinker", "техис": "Techies", "техиз": "Techies", "ио": "Io", "дум": "Doom",
    "марси": "Marci", "марс": "Mars", "магнус": "Magnus", "хускар": "Huskar",
    "клинкз": "Clinkz", "клокверк": "Clockwerk", "клок": "Clockwerk", "джакиро": "Jakiro",
    "таск": "Tusk", "терор": "Terrorblade",
    "террорблейд": "Terrorblade", "кристалка": "Crystal Maiden", "цм": "Crystal Maiden",
    "дро": "Drow Ranger", "дровка": "Drow Ranger", "дроу рейнджер": "Drow Ranger", "эмбер": "Ember Spirit",
    "шторм": "Storm Spirit", "сторм": "Storm Spirit", "войд спирит": "Void Spirit", "вк": "Wraith King",
    "скелет": "Wraith King",
    "бх": "Bounty Hunter",
}
_ALIASES = {"am": 1, "cm": 5, "sf": 11, "pa": 44, "bb": 99, "wk": 42, "tb": 109, "ember": 106, "ls": 54}
SUBSTRING_MIN = 4  # подстрока внутри слова — только от 4 символов: «od» не должен находить Bloodseeker


def update_heroes(data) -> int:
    """Дополнить/обновить справочник из ответа OpenDota /heroes ([{id, localized_name}]). Вернуть число новых."""
    added = 0
    for hero in data if isinstance(data, list) else []:
        try:
            hid, name = int(hero["id"]), hero["localized_name"]
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(name, str) or not name:
            continue
        added += hid not in HERO_NAMES
        HERO_NAMES[hid] = name
    return added


def find_hero(query: str):
    """Имя героя (регистр не важен; английское/русское, префикс слова, алиасы) → hero_id | None."""
    q = (query or "").strip().lower()
    if not q:
        return None
    if q in _ALIASES:
        return _ALIASES[q]
    names = {hid: name.lower() for hid, name in HERO_NAMES.items()}
    ru = _RU_NAMES.get(q)
    if ru:
        q = ru.lower()
    elif any("а" <= ch <= "я" or ch == "ё" for ch in q):  # кириллица: префикс русского названия
        hits = [en for key, en in _RU_NAMES.items() if key.strip().startswith(q) and len(q) >= 3]
        if hits:
            q = hits[0].lower()
    matchers = [
        lambda n: n == q,
        lambda n: n.startswith(q),
        lambda n: any(word.startswith(q) for word in n.replace("-", " ").split()),
    ]
    if len(q) >= SUBSTRING_MIN:
        matchers.append(lambda n: q in n)
    for match in matchers:
        for hid, name in names.items():
            if match(name):
                return hid
    return None


def hero_name(hero_id) -> str:
    if not hero_id:
        return "?"
    return HERO_NAMES.get(hero_id, f"hero {hero_id}")
