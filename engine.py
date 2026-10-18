"""MayhemCombo - engine: du lieu + cham diem combo augment ARAM Mayhem.

Nguon du lieu:
  * arammeta (github.com/Lanternko/ARAM-Mayhem-Database, MIT): ti le thang that
    cua tung augment theo tung tuong trong ARAM Mayhem (queue 2400).
  * CommunityDragon: ten augment tieng Viet (vi_vn).
  * Riot Data Dragon: ten tuong tieng Viet, tam danh.

Diem cua mot augment = (do hop voi tuong, tu so lieu that)
                     + (cong huong / xung dot voi augment da co)
                     + (thoi diem chon).
Don vi: "diem phan tram ti le thang" uoc tinh (vd +3.0 ~ tang 3% ti le thang).
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field

VERSION = "1.3.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))

ARAMMETA_BASES = [
    "https://raw.githubusercontent.com/Lanternko/ARAM-Mayhem-Database/main/docs/api",
    "https://arammeta.com/api",
]
CDRAGON_VN_AUGS = ("https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
                   "global/vi_vn/v1/cherry-augments.json")
DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_CHAMPS = "https://ddragon.leagueoflegends.com/cdn/{ver}/data/vi_VN/champion.json"

RARITY_VN = {"kSilver": "Bạc", "kGold": "Vàng", "kPrismatic": "Kim Cương"}
RARITY_ORDER = ["kPrismatic", "kGold", "kSilver"]


def user_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "MayhemCombo")
    os.makedirs(os.path.join(d, "cache"), exist_ok=True)
    return d


# --------------------------------------------------------------------------- utils

def norm(s: str) -> str:
    """Bo dau tieng Viet + ky tu dac biet de tim kiem: 'Vũ Khí' -> 'vu khi'."""
    if not s:
        return ""
    s = s.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def alias_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean_desc(d: str) -> str:
    d = d or ""
    d = d.replace("[數值]", "X")
    d = re.sub(r"\{\{\s*Item_Keyword_OnHit\s*\}\}", "on-hit", d)
    d = re.sub(r"\{\{\s*[Ss]pell[Nn]ame\s*\}\}", "[một kỹ năng]", d)
    d = re.sub(r"\{\{[^}]*\}\}", "", d)
    return re.sub(r"\s+", " ", d).strip()


def fmt_games(g: int) -> str:
    if g >= 1000:
        return f"{g / 1000:.1f}k".replace(".0k", "k")
    return str(g)


def http_get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"MayhemCombo/{VERSION} (personal overlay)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def cached_json(name: str, urls: list[str], max_age_s: float, log=None):
    """Tai JSON co cache tren dia. Loi mang -> dung ban cache cu (neu co)."""
    path = os.path.join(user_dir(), "cache", name)
    fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path) < max_age_s)
    if fresh:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    for url in urls:
        try:
            raw = http_get(url)
            data = json.loads(raw.decode("utf-8"))
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, path)
            return data
        except Exception as e:  # noqa: BLE001
            if log:
                log(f"tải lỗi {url}: {e}")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


# --------------------------------------------------------------------------- tags

AXIS_VN = {
    "AD": "sát thương vật lý", "AP": "sức mạnh phép", "AS": "tốc đánh", "ONHIT": "hiệu ứng đòn đánh",
    "CRIT": "chí mạng", "SPELL": "spam kỹ năng / hồi chiêu", "ULT": "chiêu cuối", "TANK": "chống chịu",
    "HP": "máu tối đa", "HEAL": "hồi máu / khiên đồng đội", "VAMP": "hút máu", "MS": "tốc chạy",
    "DASH": "kỹ năng lướt", "CC": "khống chế", "BURN": "thiêu đốt / sát thương theo thời gian",
    "SNOW": "bóng tuyết", "GOLD": "kinh tế", "RANGE": "tầm đánh", "MANA": "năng lượng (mana)",
    "DEATH": "hiệu ứng khi chết", "TAKEDOWN": "cộng dồn khi hạ gục", "BIG": "to lên", "SMALL": "nhỏ lại",
    "ITEM": "trang bị", "AUGDMG": "sát thương từ augment", "ABIL": "nâng cấp 1 kỹ năng", "SUMMON": "triệu hồi",
    "HYDRA": "Rìu Mãng Xà", "ZHONYA": "Đồng Hồ Cát", "IMMOLATE": "Giáp Mặt Trời", "STACK": "cộng dồn vĩnh viễn",
    "MELEE": "cận chiến",
}

# Nhan co che cho tung augment Mayhem (patch 16.20). Augment moi chua co o day se tu gan nhan
# tu mo ta tieng Anh (auto_tags).
_AUG_TAGS_SRC = {
    # ---- Silver
    1205: "AP:1", 2138: "TANK:.7 ABIL:1", 1007: "AD:1", 2144: "HEAL:1 ABIL:1", 2024: "CRIT:1 SPELL:.7",
    1022: "AS:1", 1025: "DEATH:1", 1026: "MS:1", 2131: "TANK:.6", 1028: "SPELL:.3 AS:.3",
    1333: "TANK:.6 MS:.3", 1308: "AP:.6 AUGDMG:1 MS:.3", 1037: "HEAL:1", 1348: "DASH:.3", 1187: "AUGDMG:.3",
    2127: "ITEM:1 AUGDMG:1", 1138: "VAMP:1", 1181: "HP:1 AS:.5 TANK:.5", 1416: "AUGDMG:1", 1105: "MS:1",
    1044: "CC:.5", 1046: "AUGDMG:.7", 2125: "MS:.5 ABIL:1", 2016: "ONHIT:1 AS:.6 CRIT:.4",
    2026: "MS:.5 TAKEDOWN:.3", 1305: "MS:1", 1051: "AS:.8 ONHIT:.6 AUGDMG:.5", 1314: "HEAL:.4 TANK:.3",
    1056: "MANA:1 HP:.8", 1057: "TANK:.6", 1060: "VAMP:.5 MANA:.3", 1347: "MS:.4 TANK:.4", 2018: "SPELL:1",
    1170: "RANGE:1 AS:.3", 1073: "DASH:1 MS:.7", 2073: "VAMP:.8 ABIL:1", 1136: "CC:1 AD:.3 AP:.3",
    2088: "SNOW:1", 1076: "HEAL:1", 1386: "AS:.3", 1214: "SPELL:.6", 1204: "STACK:1", 1404: "GOLD:1",
    2076: "TANK:.8 ABIL:1", 1315: "DASH:1 TANK:.4", 1080: "CRIT:.8 TANK:.8", 1237: "GOLD:.3", 2136: "ABIL:1",
    1415: "SPELL:.7 CRIT:.6 AUGDMG:.8", 1087: "AS:.8 ONHIT:.8 RANGE:.3", 1112: "ULT:1 TANK:.4",
    1320: "GOLD:.7 AD:.5 CRIT:.4", 2157: "AD:.4 TANK:.5 VAMP:.4", 1319: "GOLD:.7 TANK:.8 BURN:.4 IMMOLATE:1",
    1318: "GOLD:.7 AP:.6 ITEM:.5 ZHONYA:1", 1034: "TANK:.5", 1097: "AP:1", 2009: "CRIT:1 AS:.8", 1206: "AD:1",
    # ---- Gold
    1141: "HEAL:1", 1002: "ITEM:1", 2111: "ABIL:1 AD:.3", 1180: "AP:1 TANK:.4", 1103: "SPELL:.7 ABIL:1",
    1150: "SPELL:.7 ABIL:1", 1151: "SPELL:.7 ABIL:1", 1013: "HP:1 TANK:.8", 2078: "ABIL:1 CC:.4",
    2128: "BURN:1 GOLD:.6", 1118: "HEAL:1 CRIT:.8", 1356: "CRIT:1 AS:.6 AUGDMG:.7", 1328: "CRIT:1 AS:1",
    1020: "TANK:.6 VAMP:.3", 1301: "HEAL:.5 TANK:.3", 1384: "GOLD:1", 2091: "AUGDMG:1 VAMP:.3 AD:.3",
    1029: "ONHIT:1 SPELL:.6", 1036: "BURN:1 ONHIT:.8 AS:.7", 1116: "DASH:.3", 1038: "AD:.3 AP:.3 TAKEDOWN:.3",
    2103: "SPELL:.6 AP:.6 RANGE:.3", 1322: "AS:.7 MS:.5 TAKEDOWN:.7", 1401: "HP:.8 TANK:.6 BIG:.6 CC:.3",
    2042: "", 1149: "TANK:1 CC:.6", 1047: "CRIT:1", 1211: "ULT:1", 2096: "AS:.8 RANGE:.5 ABIL:1",
    1133: "SPELL:.8 AP:.3 AUGDMG:1", 1129: "AP:.8 AS:.8", 2133: "HEAL:.6 AS:.4 ABIL:1", 1104: "SUMMON:1",
    2043: "VAMP:.4", 1326: "TAKEDOWN:.8 MS:.5", 1061: "AUGDMG:1", 2082: "VAMP:.4 HEAL:.3",
    1063: "DASH:1 TANK:.7", 2119: "", 1311: "MANA:1 HEAL:.4 SPELL:.4", 2137: "TANK:.4 MS:.3",
    1390: "AP:1 SPELL:.5 STACK:.3", 1358: "SNOW:1", 2139: "TANK:.8", 2102: "HP:.8 TANK:.6 BURN:.7",
    2100: "ABIL:1 SPELL:.5", 2116: "ABIL:1", 2064: "ABIL:1 DASH:.6", 2077: "ABIL:1 CC:.8 VAMP:.4",
    1068: "SPELL:1", 1067: "ABIL:1 VAMP:.5", 1071: "RANGE:1 AS:.3", 1072: "SPELL:.3 HEAL:.3",
    2032: "DEATH:1", 2034: "SNOW:1", 1373: "SMALL:1 TAKEDOWN:.8 SPELL:.5 MS:.4", 1074: "ONHIT:.8 AS:.5 TANK:.3",
    1113: "SPELL:.8 RANGE:.3", 2080: "SNOW:1", 1420: "HEAL:1", 1375: "CC:1 HP:.8 STACK:.3",
    1077: "CRIT:1 VAMP:.8", 1345: "TAKEDOWN:.8", 1403: "GOLD:1", 1152: "HP:1 TANK:.8",
    1353: "HP:1 TANK:.8 TAKEDOWN:.7 BIG:.8", 2129: "ABIL:1", 2065: "ABIL:1 CC:.6", 1084: "AD:.5 AP:.5",
    2083: "TAKEDOWN:.4 AD:.3 AP:.3", 1238: "GOLD:.3", 1336: "CRIT:1 GOLD:.6",
    2140: "SPELL:.5 VAMP:.5 AD:.5 GOLD:.6 HYDRA:1", 1996: "SPELL:.6 AS:.3 GOLD:.6", 2143: "AD:.5 TANK:.4 GOLD:.6",
    1092: "BURN:.8 ITEM:.8 CRIT:.8", 2132: "VAMP:1", 1005: "HEAL:1 MS:.4", 1098: "SPELL:.6 MS:.8",
    2089: "GOLD:.7 TAKEDOWN:.5",
    # ---- Prismatic
    2087: "SPELL:1", 1004: "SPELL:1 HEAL:.3", 1329: "SNOW:1", 1006: "AD:.3", 1011: "ULT:1 TANK:.4",
    1015: "VAMP:1 HEAL:.6", 1310: "DEATH:.8", 1018: "CC:1 TANK:.8", 1323: "CC:1 AUGDMG:.6",
    1019: "DASH:1 SPELL:.5", 2063: "", 2010: "CRIT:1 ONHIT:1 AS:.5", 1134: "AD:.8 AS:.6 VAMP:.5 MELEE:1",
    2031: "DEATH:1", 2006: "TAKEDOWN:.4 VAMP:.3", 1225: "AS:1 ONHIT:1", 1027: "DASH:1", 2062: "ABIL:1",
    2004: "HEAL:1", 1331: "HEAL:1", 2098: "AS:.4 MS:.4 VAMP:.3", 1030: "AP:1 SPELL:1",
    1220: "AS:1 AUGDMG:.7 RANGE:.3", 1194: "ULT:1 CC:.5", 1344: "ULT:1 TANK:.5 VAMP:.5",
    1195: "SMALL:1 MS:.5", 1325: "", 1335: "GOLD:.6 MS:.3", 1041: "HP:1 TANK:.8 BIG:1", 1389: "AD:.4 AP:.4",
    2107: "DEATH:.6", 2095: "GOLD:1", 1392: "SNOW:1", 1361: "TANK:1 HP:.6 BURN:.5 IMMOLATE:1",
    1045: "BURN:1 SPELL:.8 AP:.5", 1388: "SPELL:1 TAKEDOWN:.5", 1048: "CRIT:1 SPELL:.8", 1337: "GOLD:.5",
    1053: "DEATH:.5", 1054: "AS:.7 SPELL:.6 AD:.4 AP:.4", 2055: "ABIL:1", 1058: "ONHIT:1 AS:1 SPELL:.7",
    1332: "AP:.8 VAMP:.6 SPELL:.4", 1062: "", 2123: "ABIL:1 SPELL:.7", 12317: "", 2135: "ABIL:1 AS:.6",
    2046: "", 1421: "CC:.5 TANK:.3", 1324: "HEAL:1 TANK:.8", 2099: "TAKEDOWN:.6 SPELL:.4",
    1115: "RANGE:1 AS:.3", 2072: "ABIL:1", 2104: "HEAL:1", 2115: "CC:.5", 1402: "GOLD:1",
    1413: "ULT:1 TANK:.7 CC:.5", 2134: "ULT:1 AUGDMG:.5", 1079: "AS:.8 AD:.3", 1081: "MS:1 AS:1",
    1001: "TANK:.8 BIG:.6", 1243: "GOLD:.3", 2005: "AUGDMG:.3", 2054: "ABIL:1", 2118: "ULT:1",
    1349: "ULT:1 SPELL:.5", 1088: "ULT:1", 2141: "HYDRA:1 AD:.5 VAMP:.3", 1379: "AS:.6 HEAL:.6",
    1154: "TAKEDOWN:.6 GOLD:.4", 1095: "HEAL:1", 1156: "AP:1 ZHONYA:1",
}


def _parse_tags(s: str) -> dict:
    out = {}
    for part in s.split():
        k, v = part.split(":")
        out[k] = float(v)
    return out


AUG_TAGS = {k: _parse_tags(v) for k, v in _AUG_TAGS_SRC.items()}

_CAT_TAGS = {"ad": ("AD", .7), "ap": ("AP", .7), "crit": ("CRIT", .8), "tank": ("TANK", .6),
             "support": ("HEAL", .7), "cd": ("SPELL", .6), "gold": ("GOLD", .7)}
_DESC_TAGS = [
    (r"attack speed", "AS", .7), (r"on-hit|onhit", "ONHIT", .7), (r"ultimate", "ULT", .7),
    (r"max(imum)? health", "HP", .5), (r"omnivamp|life ?steal|heals? you", "VAMP", .5),
    (r"move(ment)? speed", "MS", .5), (r"\bdash|blink|teleport", "DASH", .6),
    (r"immobiliz|ground", "CC", .7), (r"\bburn|damage over time", "BURN", .7), (r"snowball", "SNOW", 1),
    (r"attack range", "RANGE", .8), (r"\bmana\b", "MANA", .6), (r"when you die|on death|upon death", "DEATH", .8),
    (r"takedown", "TAKEDOWN", .5), (r"\[một kỹ năng\]", "ABIL", 1), (r"ability haste", "SPELL", .6),
    (r"ability power", "AP", .6), (r"attack damage", "AD", .6), (r"crit", "CRIT", .6),
]


def auto_tags(aug: dict) -> dict:
    t: dict = {}
    for c in aug.get("cats", []):
        if c in _CAT_TAGS:
            k, v = _CAT_TAGS[c]
            t[k] = max(t.get(k, 0), v)
    d = (aug.get("desc") or "").lower()
    for rx, k, v in _DESC_TAGS:
        if re.search(rx, d):
            t[k] = max(t.get(k, 0), v)
    return t


# Ma tran cong huong giua cac huong (axis). Doi xung.
_AXIS_SYN = {
    ("AD", "AD"): .5, ("AP", "AP"): .6, ("AS", "AS"): .5, ("ONHIT", "ONHIT"): .7, ("CRIT", "CRIT"): .7,
    ("SPELL", "SPELL"): .6, ("ULT", "ULT"): .8, ("TANK", "TANK"): .4, ("HP", "HP"): .7, ("HEAL", "HEAL"): .7,
    ("VAMP", "VAMP"): .3, ("MS", "MS"): .5, ("DASH", "DASH"): .8, ("CC", "CC"): .7, ("BURN", "BURN"): .8,
    ("SNOW", "SNOW"): .9, ("RANGE", "RANGE"): .2, ("MANA", "MANA"): .8, ("DEATH", "DEATH"): .7,
    ("TAKEDOWN", "TAKEDOWN"): .4, ("BIG", "BIG"): .6, ("SMALL", "SMALL"): .6, ("ITEM", "ITEM"): .4,
    ("AUGDMG", "AUGDMG"): .5, ("SUMMON", "SUMMON"): .5, ("HYDRA", "HYDRA"): 1.0, ("ZHONYA", "ZHONYA"): .8,
    ("IMMOLATE", "IMMOLATE"): 1.0,
    ("AS", "ONHIT"): .8, ("AS", "CRIT"): .5, ("CRIT", "AD"): .4, ("AD", "AS"): .3, ("SPELL", "AP"): .5,
    ("SPELL", "BURN"): .4, ("AP", "BURN"): .3, ("TANK", "HP"): .6, ("HP", "VAMP"): .2, ("TANK", "VAMP"): .3,
    ("HEAL", "VAMP"): .3, ("MS", "DASH"): .3, ("CC", "TANK"): .3, ("AUGDMG", "ITEM"): .7, ("BURN", "ITEM"): .4,
    ("CRIT", "SPELL"): .2, ("RANGE", "AS"): .4, ("MANA", "HP"): .3, ("MANA", "SPELL"): .3,
    ("TAKEDOWN", "SPELL"): .2, ("BIG", "HP"): .6, ("BIG", "TANK"): .4, ("TANK", "HEAL"): .2,
    ("BIG", "SMALL"): -1.0, ("RANGE", "MELEE"): -1.5,
}
AXIS_SYN: dict = {}
for (a, b), v in _AXIS_SYN.items():
    AXIS_SYN[(a, b)] = v
    AXIS_SYN[(b, a)] = v

# Combo / xung dot cu the. (nhom A, nhom B, diem, giai thich).
_ULT_AUGS = [1011, 1194, 1344, 1211, 1413, 2134, 2118, 1349, 1088, 1112]
_CRIT_CHANCE = [1047, 2009, 1415, 1356, 1077, 1118, 2024, 1080, 1336, 1328]
_ONHIT_FX = [1036, 2016, 1074]
_AS_AUGS = [1022, 2009, 1081, 1328, 1225, 1322, 2096, 1079, 1058]
_HP_AUGS = [1041, 1353, 1013, 1152, 1401, 1375, 1056]
_MS_AUGS = [1105, 1305, 1081, 1098, 1073, 1195, 1373, 1322]
_AUG_DMG = [1133, 1415, 1356, 1308, 1416, 1061, 2091, 1051, 1220, 1323, 2139, 1046, 2134, 1025, 2031, 1015,
            1335, 2103]
_SUSTAIN = [1138, 2132, 1077, 1060, 2043, 2082, 1020, 2073, 1067, 1344]
_SHIELD_SRC = [1180, 1333, 1315, 1057, 2131, 1018, 1344, 2137]
_DEATH = [1025, 2031, 1310, 2032]

_PAIR_RULES = [
    # ---------------- combo manh
    ([1029], [1058], 4.0, "kỹ năng kích hoạt hiệu ứng đòn đánh → mỗi kỹ năng trúng đều giảm hồi chiêu (combo nổi tiếng)"),
    ([1029], [1036], 2.5, "kỹ năng cũng gây thiêu đốt cộng dồn vô hạn"),
    ([1029], [2016], 2.0, "kỹ năng cũng gây thêm sát thương phép on-hit"),
    ([1029], [1074], 1.5, "kỹ năng cũng làm giảm sát thương của mục tiêu"),
    ([1058], [1022, 2009, 1081, 1328, 1079], 1.5, "đánh nhanh hơn → giảm hồi chiêu nhanh hơn"),
    ([1058], [1225], 2.5, "mỗi đòn bắn thêm 1 tia on-hit → giảm hồi chiêu gấp đôi"),
    ([1058], [2010], 2.0, "đòn chí mạng kích hoạt on-hit 2 lần → giảm hồi chiêu 2 lần"),
    ([1058], [1087], 1.0, "tia phụ cũng kích hoạt on-hit"),
    ([1048], [1047, 1415, 1077, 2024], 2.5, "kỹ năng chí mạng + thêm tỉ lệ chí mạng"),
    ([1048], [2009, 1356, 1118, 1336, 1092], 1.5, "kỹ năng chí mạng + thêm tỉ lệ chí mạng"),
    ([1048], [1080], 1.0, "thêm tỉ lệ chí mạng cho kỹ năng"),
    ([1092], [1036, 1045], 2.2, "sát thương thiêu đốt có thể chí mạng"),
    ([1092], [2102, 1319, 1361, 2127, 1047], 1.5, "thiêu đốt / trang bị có thể chí mạng"),
    ([1092], [2128, 1046], 0.8, "thiêu đốt có thể chí mạng"),
    ([1045], [2128], 2.5, "thiêu đốt từ kỹ năng → ra vàng liên tục"),
    ([1045], [1036, 2102], 2.0, "thêm nguồn thiêu đốt → giảm hồi chiêu nhanh hơn"),
    ([1045], [1319, 1361], 1.0, "Giáp Mặt Trời thiêu đốt → giảm hồi chiêu"),
    ([2128], [1036, 2102], 1.5, "thêm nguồn thiêu đốt → ra thêm vàng"),
    ([2128], [1319, 1361], 1.0, "Giáp Mặt Trời thiêu đốt → ra thêm vàng"),
    ([2102], [1041, 1353, 1152], 2.0, "thiêu đốt tăng theo máu tối đa"),
    ([2102], [1013, 1361], 1.5, "thiêu đốt tăng theo máu tối đa"),
    ([2102], [1319], 1.0, "cùng lối tank thiêu đốt"),
    ([1181], [1041, 1353, 1152], 2.0, "đòn đánh gây sát thương theo máu tối đa"),
    ([1181], [1013, 1401, 1375], 1.5, "đòn đánh gây sát thương theo máu tối đa"),
    ([1181], [1056], 1.0, "thêm máu tối đa → đánh đau hơn"),
    ([1013], [1041, 1353], 1.5, "chồng máu tối đa"),
    ([1041], [1353], 1.5, "chồng máu + kích thước"),
    ([1041], [1001], 1.0, "chồng chống chịu + kích thước"),
    ([1373], [1195], 3.0, "càng nhỏ càng gây thêm sát thương lên mục tiêu to"),
    ([1205], [1097, 1030, 1180], 1.5, "chuyển SMVL thành SMPT rồi nhân thêm"),
    ([1205], [1129], 2.0, "đồ AD thành SMPT, đòn đánh lại gây sát thương theo SMPT"),
    ([1205], [1390, 1156], 1.0, "cùng hướng SMPT"),
    ([1030], [1390], 2.0, "SMPT cộng dồn → thêm điểm hồi kỹ năng"),
    ([1030], [1097], 1.5, "thêm SMPT → thêm điểm hồi kỹ năng"),
    ([1030], [1388], 1.0, "chồng điểm hồi kỹ năng"),
    ([1098], [1068, 1388, 1030, 2018], 1.5, "điểm hồi kỹ năng → tốc chạy"),
    ([1098], [2024, 2087], 0.8, "điểm hồi kỹ năng → tốc chạy"),
    ([1098], [1081, 1026], 2.0, "tốc chạy chuyển thành tốc đánh / sát thương"),
    ([1081], [1105, 1305], 1.5, "thêm tốc chạy → thêm tốc đánh"),
    ([1081], [1026], 2.0, "tốc chạy cao → vừa đánh nhanh vừa đánh đau"),
    ([1081], [1073, 1322, 1195], 1.0, "thêm tốc chạy → thêm tốc đánh"),
    ([1026], [1105, 1305], 2.0, "thêm tốc chạy → thêm sát thương"),
    ([1026], [1073, 1195, 1373], 1.5, "thêm tốc chạy → thêm sát thương"),
    ([1026], [1335], 1.0, "thêm tốc chạy → thêm sát thương"),
    ([2010], [1047, 2009], 2.0, "nhiều chí mạng → on-hit kích hoạt 2 lần thường xuyên"),
    ([2010], [1328], 1.5, "nhiều chí mạng → on-hit kích hoạt 2 lần"),
    ([2010], [2016], 2.0, "on-hit phép kích hoạt 2 lần và cũng chí mạng được"),
    ([2010], [1036, 1225], 1.5, "on-hit kích hoạt 2 lần"),
    ([2010], [1074], 1.0, "on-hit kích hoạt 2 lần"),
    ([1225], [2016, 1036], 1.5, "tia phụ cũng mang hiệu ứng on-hit"),
    ([1225], [1074, 1087], 1.0, "thêm nguồn on-hit"),
    ([1087], [2016, 1036], 1.0, "mục tiêu phụ cũng dính on-hit"),
    ([1356], [1047, 2009], 1.5, "nhiều chí mạng → bắn thêm tên lửa"),
    ([2127], _AUG_DMG, 1.5, "tăng sát thương của augment này"),
    ([1015], _SUSTAIN, 1.5, "mỗi lần hồi máu lại gây sát thương"),
    ([1025], [2031, 1310], 2.0, "chồng hiệu ứng khi chết"),
    ([1025], [2032], 1.5, "chồng hiệu ứng khi chết"),
    ([2031], [1310], 1.5, "chồng hiệu ứng khi chết"),
    ([2031, 1310], [2032], 1.0, "chồng hiệu ứng khi chết"),
    ([2107], _DEATH, 1.5, "chết kích hoạt hiệu ứng rồi hồi sinh"),
    ([2107], [1053], 1.5, "thêm 1 lần hồi sinh → thêm 1 lần lớn mạnh"),
    ([1325], [1025], 1.0, "sát thương chuẩn + nổ khi chết"),
    ([1156], [1318], 3.0, "Đồng Hồ Cát nâng cấp: đi lại được khi bất tử, hồi chiêu ngắn"),
    ([1002], [1318], 1.5, "giảm hồi chiêu Đồng Hồ Cát"),
    ([1002], [1156], 1.0, "giảm hồi chiêu trang bị kích hoạt"),
    ([1361], [1319], 3.0, "cùng nâng cấp Giáp Mặt Trời / Hollow Radiance"),
    ([2141], [2140], 2.5, "cùng lối Rìu Mãng Xà"),
    ([1152], [1353], 1.0, "chồng máu"),
    ([1311], [1056], 2.5, "cùng tăng theo năng lượng tối đa"),
    ([1311], [1060], 0.5, "hồi năng lượng"),
    ([1324], [1001], 1.5, "giáp/kháng phép → tăng hồi máu và khiên"),
    ([1324], [1149, 2076, 1063], 1.0, "giáp/kháng phép → tăng hồi máu và khiên"),
    ([1314], [1180], 2.0, "có khiên → thêm sức mạnh thích ứng"),
    ([1314], [1315, 1057, 1018], 1.5, "có khiên → thêm sức mạnh thích ứng"),
    ([1314], [1333, 2131, 1344, 2137], 1.0, "có khiên → thêm sức mạnh thích ứng"),
    ([1180], [1097, 1390], 1.0, "thêm SMPT → khiên to hơn"),
    ([1149], [1018], 1.0, "khống chế kích hoạt Dư Chấn + khiên"),
    ([2118], [1088, 1011, 1344, 1194, 1211, 1413, 2134], 2.0, "chiêu cuối hồi cực nhanh"),
    ([2118], [1112, 1349], 1.5, "chiêu cuối hồi cực nhanh"),
    ([1088], [1011, 1344, 1194, 2134, 1349], 2.5, "dùng chiêu cuối 2 lần → kích hoạt 2 lần"),
    ([1088], [1211, 1413], 2.0, "dùng chiêu cuối 2 lần → kích hoạt 2 lần"),
    ([1088], [1112], 1.5, "dùng chiêu cuối 2 lần → kích hoạt 2 lần"),
    ([1349], [1011, 1344, 1194, 1211, 1413, 2134, 1112], 1.5, "chiêu cuối hồi nhanh hơn"),
    ([2018], [1068, 2087, 1030, 1388], 1.0, "chồng điểm hồi kỹ năng"),
    # ---------------- xung dot
    ([1004], _ULT_AUGS, -8.0, "Đơn Giản Hóa khoá chiêu cuối → augment chiêu cuối vô dụng"),
    ([1205], [1206], -8.0, "hai augment đổi chỉ số ngược chiều nhau"),
    ([1206], [1030], -4.0, "SMPT bị đổi hết thành SMVL → không còn điểm hồi kỹ năng"),
    ([1206], [1180, 1129], -3.0, "SMPT bị đổi hết thành SMVL"),
    ([1206], [1156], -1.0, "SMPT bị đổi hết thành SMVL"),
    ([2018], [1022, 1081], -3.0, "tốc đánh bị đổi hết thành điểm hồi kỹ năng"),
    ([2018], [1328, 1079], -2.5, "tốc đánh bị đổi hết thành điểm hồi kỹ năng"),
    ([2018], [1225, 1058], -2.0, "tốc đánh bị đổi hết thành điểm hồi kỹ năng"),
    ([2018], [2096, 2009, 1322], -1.2, "phần tốc đánh bị đổi thành điểm hồi kỹ năng"),
    ([1134], [1115], -5.0, "đã biến thành cận chiến → tầm đánh vô nghĩa"),
    ([1134], [1170, 1071], -4.0, "đã biến thành cận chiến → tầm đánh vô nghĩa"),
    ([1134], [2096], -1.5, "đã biến thành cận chiến → tầm đánh vô nghĩa"),
    ([1195], [1041], -5.0, "Đồ Tể Khổng Lồ cần bạn nhỏ, augment này làm bạn to ra"),
    ([1195], [1353], -4.0, "Đồ Tể Khổng Lồ cần bạn nhỏ, augment này làm bạn to ra"),
    ([1195], [1001], -3.0, "Đồ Tể Khổng Lồ cần bạn nhỏ, augment này làm bạn to ra"),
    ([1195], [1401], -2.0, "Đồ Tể Khổng Lồ cần bạn nhỏ, augment này làm bạn to ra"),
    ([1373], [1041, 1353], -1.5, "một cái làm nhỏ, một cái làm to"),
    ([2118], [1068, 1103, 1150, 1151, 1019], -2.0, "Ult Bot chỉ cho điểm hồi kỹ năng vào chiêu cuối"),
    ([2118], [1388, 1030, 2018, 1214, 2024, 1098], -1.0, "Ult Bot chỉ cho điểm hồi kỹ năng vào chiêu cuối"),
    ([2118], [1004], -8.0, "Đơn Giản Hóa khoá chiêu cuối"),
]

PAIR_RULES: dict = {}
for _A, _B, _v, _txt in _PAIR_RULES:
    for _a in _A:
        for _b in _B:
            if _a == _b:
                continue
            for key in ((_a, _b), (_b, _a)):
                cur = PAIR_RULES.get(key)
                if cur is None or abs(_v) > abs(cur[0]):
                    PAIR_RULES[key] = (_v, _txt)

QUEST_IDS = {1152, 1361, 1156, 2141, 1154, 2103, 2100, 2116, 2055, 2046, 2102}
PURE_ECON_IDS = {1384, 1404, 1403, 1402, 2095, 2089}
RANDOM_IDS = {1237, 1238, 1243, 12317}


# --------------------------------------------------------------------------- data
# Du lieu kem theo app:  data/core.json (augment + tuong, ~150KB)
#                        data/champs/<id>.json (so lieu augment theo tung tuong, nap khi can)
# -> chi giu trong RAM so lieu cua vai tuong gan nhat (tiet kiem RAM).

BUNDLED_CORE = os.path.join(APP_DIR, "data", "core.json")
BUNDLED_CHAMPS_DIR = os.path.join(APP_DIR, "data", "champs")
CDRAGON_EN_AUGS = ("https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
                   "global/default/v1/cherry-augments.json")
CHAMP_CACHE_MAX = 4


def compact_core(tier: dict) -> dict:
    augs = {}
    for k, a in (tier.get("augs") or {}).items():
        if not str(k).isdigit():
            continue
        augs[str(k)] = {
            "en": a.get("name_en") or a.get("name") or f"#{k}",
            "rarity": a.get("rarity"),
            "cats": a.get("cats") or [],
            "desc": clean_desc(a.get("desc_en", "")),
            "wr": a.get("rawWr") or a.get("wr"),
            "lift": a.get("lift"),
            "g": a.get("g") or 0,
        }
    champs = {}
    for k, c in (tier.get("champs") or {}).items():
        if not str(k).isdigit():
            continue
        champs[str(k)] = {
            "alias": c.get("alias"), "en": c.get("name_en"), "tags": c.get("tags") or [],
            "wr": c.get("rawWr") or c.get("wr"), "g": c.get("g") or 0, "comp": c.get("comp") or {},
        }
    return {
        "patch": tier.get("patch_prefix") or "",
        "ddv": tier.get("ddv") or "",
        "detailVersion": tier.get("detailVersion") or "",
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "augs": augs, "champs": champs,
    }


def compact_champ(cf: dict) -> dict:
    """File champions/<id>.json cua arammeta -> {a: {aug: [tran, ti_le_thang]}, s: {aug: [[tran, tlt] x4 luot]}}"""
    a = {str(p["id"]): [p.get("g", 0), p.get("wr")] for p in cf.get("poolAugments", []) if "id" in p}
    s = {}
    for part in ("top", "bot"):
        for rows in (cf.get(part) or {}).values():
            for row in rows or []:
                sl = row.get("slots")
                if sl and str(row.get("id")) not in s:
                    s[str(row["id"])] = [[(x or {}).get("g", 0), (x or {}).get("rawWr", (x or {}).get("wr"))]
                                         for x in sl]
    return {"a": a, "s": s}


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _write_json(path: str, obj):
    try:
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def fetch_updates(ddv_hint: str = "", log=None) -> dict | None:
    """Tai du lieu moi (goi o luong nen, KHONG dung toi Engine). Tra ve dict nho gon de apply_updates()."""
    out: dict = {}
    tier = cached_json("tier-list.json", [f"{b}/tier-list.json" for b in ARAMMETA_BASES], 6 * 3600, log)
    if tier and tier.get("augs"):
        out["core"] = compact_core(tier)
    del tier
    names: dict = {}
    vn = cached_json("vi_vn-cherry-augments.json", [CDRAGON_VN_AUGS], 24 * 3600, log)
    if isinstance(vn, list):
        names["vn_aug"] = {str(r.get("id")): (r.get("nameTRA") or "").strip() for r in vn
                           if isinstance(r, dict) and r.get("nameTRA")}
    en = cached_json("en-cherry-augments.json", [CDRAGON_EN_AUGS], 24 * 3600, log)
    if isinstance(en, list):
        names["en_aug"] = {str(r.get("id")): (r.get("nameTRA") or "").strip() for r in en
                           if isinstance(r, dict) and r.get("nameTRA")}
    del vn, en
    ver = (out.get("core") or {}).get("ddv") or ddv_hint
    if not ver:
        vers = cached_json("ddragon-versions.json", [DDRAGON_VERSIONS], 24 * 3600, log)
        ver = vers[0] if isinstance(vers, list) and vers else ""
    if ver:
        dd = cached_json(f"ddragon-vi_VN-{ver}.json", [DDRAGON_CHAMPS.format(ver=ver)], 7 * 24 * 3600, log)
        if isinstance(dd, dict) and dd.get("data"):
            vc, rg, al = {}, {}, {}
            for alias, c in dd["data"].items():
                key = str(c.get("key") or "")
                if not key.isdigit():
                    continue
                vc[key] = c.get("name") or alias
                r = (c.get("stats") or {}).get("attackrange")
                if r:
                    rg[key] = float(r)
                al[alias_key(alias)] = int(key)
            names.update(vn_champ=vc, champ_range=rg, dd_alias=al)
    if names:
        out["names"] = names
    if not out:
        return None
    # Luu ban gon de lan sau mo app dung ngay (ke ca khi mat mang).
    if out.get("core"):
        _write_json(os.path.join(user_dir(), "cache", "core-compact.json"), out["core"])
    if names:
        old = _read_json(os.path.join(user_dir(), "cache", "names-compact.json")) or {}
        old.update(names)
        _write_json(os.path.join(user_dir(), "cache", "names-compact.json"), old)
    return out


def fetch_champ(cid: int, detail_version: str, log=None) -> dict | None:
    """Tai so lieu 1 tuong (luong nen). Tra ve ban gon {a, s}."""
    name = f"champ-{cid}-{detail_version or 'x'}.json"
    path = os.path.join(user_dir(), "cache", f"champc-{cid}-{detail_version or 'x'}.json")
    got = _read_json(path)
    if got and got.get("a"):
        return got
    cf = cached_json(name, [f"{b}/champions/{cid}.json" for b in ARAMMETA_BASES], 12 * 3600, log)
    if cf and cf.get("poolAugments"):
        comp = compact_champ(cf)
        _write_json(path, comp)
        try:
            os.remove(os.path.join(user_dir(), "cache", name))  # chi giu ban gon
        except OSError:
            pass
        return comp
    return None


@dataclass
class Reason:
    kind: str  # "+", "-", "i", "!"
    text: str
    short: str = ""  # ban rut gon cho giao dien gon


@dataclass
class Scored:
    aid: int
    total: float
    champ: float
    syn: float
    timing: float
    reasons: list = field(default_factory=list)
    grade: str = ""
    games: int = 0


def grade_of(total: float) -> str:
    if total >= 3.0:
        return "Rất mạnh"
    if total >= 1.2:
        return "Tốt"
    if total >= -0.5:
        return "Ổn"
    if total >= -2.0:
        return "Yếu"
    return "Tránh"


class Engine:
    K_SHRINK = 250.0

    def __init__(self, log=None):
        self.log = log or (lambda *_: None)
        self.patch = ""
        self.ddv = ""
        self.detail_version = ""
        self.source = ""
        self.augs: dict[int, dict] = {}
        self.champs: dict[int, dict] = {}
        self.slots: dict[int, dict] = {}       # cache LRU theo tuong
        self.champ_augs: dict[int, dict] = {}  # cache LRU theo tuong
        self.vn_aug: dict[int, str] = {}
        self.en_aug: dict[int, str] = {}
        self.vn_champ: dict[int, str] = {}
        self.champ_range: dict[int, float] = {}
        self.alias_to_cid: dict[str, int] = {}
        self.tags: dict[int, dict] = {}
        self._pct_cache: dict[str, list] = {}
        self._aug_index: list = []
        self._champ_index: list = []
        self._ocr_index = None
        self._fresh_champs: set = set()
        core = _read_json(BUNDLED_CORE)
        cached = _read_json(os.path.join(user_dir(), "cache", "core-compact.json"))
        if cached and cached.get("augs") and (not core or str(cached.get("detailVersion", "")) >=
                                              str(core.get("detailVersion", ""))):
            self.apply_core(cached, source="bản đã tải trước")
        elif core:
            self.apply_core(core, source="kèm theo app")
        else:
            self.log("không đọc được dữ liệu kèm theo app")
        names = _read_json(os.path.join(user_dir(), "cache", "names-compact.json"))
        if names:
            self.apply_names(names)

    # ------------------------------------------------------------- loading
    def apply_core(self, core: dict, source: str):
        if core.get("detailVersion") != self.detail_version:
            self.champ_augs, self.slots, self._fresh_champs = {}, {}, set()
        self.patch = core.get("patch") or self.patch
        self.ddv = core.get("ddv") or self.ddv
        self.detail_version = core.get("detailVersion") or self.detail_version
        self.augs = {int(k): v for k, v in core.get("augs", {}).items()}
        self.champs = {int(k): v for k, v in core.get("champs", {}).items()}
        self.source = source
        self.alias_to_cid.update({alias_key(c.get("alias")): cid for cid, c in self.champs.items() if c.get("alias")})
        self.tags = {aid: AUG_TAGS.get(aid) if aid in AUG_TAGS else auto_tags(a) for aid, a in self.augs.items()}
        self._pct_cache = {}
        self._rebuild_index()

    def apply_names(self, names: dict):
        for k, v in (names.get("vn_aug") or {}).items():
            if str(k).isdigit() and v:
                self.vn_aug[int(k)] = v
        for k, v in (names.get("en_aug") or {}).items():
            if str(k).isdigit() and v:
                self.en_aug[int(k)] = v
        for k, v in (names.get("vn_champ") or {}).items():
            if str(k).isdigit() and v:
                self.vn_champ[int(k)] = v
        for k, v in (names.get("champ_range") or {}).items():
            if str(k).isdigit():
                self.champ_range[int(k)] = float(v)
        for k, v in (names.get("dd_alias") or {}).items():
            self.alias_to_cid.setdefault(k, int(v))
        self._rebuild_index()

    def apply_updates(self, upd: dict) -> str:
        msgs = []
        if upd.get("core"):
            self.apply_core(upd["core"], source="arammeta (mới nhất)")
            msgs.append(f"dữ liệu patch {self.patch}")
        if upd.get("names"):
            self.apply_names(upd["names"])
            if upd["names"].get("vn_aug"):
                msgs.append("tên augment tiếng Việt")
            if upd["names"].get("vn_champ"):
                msgs.append("tên tướng tiếng Việt")
        return ", ".join(msgs)

    def set_champ_data(self, cid: int, comp: dict | None, fresh: bool = False):
        if not comp:
            return
        self.champ_augs.pop(cid, None)
        self.slots.pop(cid, None)
        self.champ_augs[cid] = {int(a): v for a, v in (comp.get("a") or {}).items()}
        self.slots[cid] = {int(a): v for a, v in (comp.get("s") or {}).items()}
        if fresh:
            self._fresh_champs.add(cid)
        while len(self.champ_augs) > CHAMP_CACHE_MAX:  # bo tuong cu nhat khoi RAM
            old = next(iter(self.champ_augs))
            self.champ_augs.pop(old, None)
            self.slots.pop(old, None)
            self._fresh_champs.discard(old)

    def _ensure_local(self, cid):
        if cid is None or cid in self.champ_augs:
            return
        comp = _read_json(os.path.join(user_dir(), "cache", f"champc-{cid}-{self.detail_version or 'x'}.json"))
        fresh = bool(comp)
        if not comp:
            comp = _read_json(os.path.join(BUNDLED_CHAMPS_DIR, f"{cid}.json"))
        if comp:
            self.set_champ_data(cid, comp, fresh=fresh)

    def champ_pool(self, cid) -> dict:
        self._ensure_local(cid)
        return self.champ_augs.get(cid, {}) if cid is not None else {}

    def champ_slots(self, cid) -> dict:
        self._ensure_local(cid)
        return self.slots.get(cid, {}) if cid is not None else {}

    # ------------------------------------------------------------- names / search
    prefer_en = False  # True: hien ten tieng Anh (khop voi client game tieng Anh)

    def aug_name(self, aid: int) -> str:
        en = self.en_aug.get(aid) or (self.augs.get(aid) or {}).get("en")
        if self.prefer_en:
            return en or self.vn_aug.get(aid) or f"#{aid}"
        return self.vn_aug.get(aid) or en or f"#{aid}"

    def aug_name_both(self, aid: int) -> str:
        vn = self.vn_aug.get(aid)
        en = (self.augs.get(aid) or {}).get("en", "")
        if vn and norm(vn) != norm(en):
            return f"{vn} ({en})"
        return en or vn or f"#{aid}"

    def champ_name(self, cid: int | None) -> str:
        if cid is None:
            return ""
        return self.vn_champ.get(cid) or (self.champs.get(cid) or {}).get("en") or f"#{cid}"

    def ocr_index(self):
        """(dict ten_chuan->id cho khop chinh xac, list (id, ten_chuan, do_hiem) cho khop gan dung)."""
        if self._ocr_index is None:
            exact: dict = {}
            fuzzy = []
            for aid, a in self.augs.items():
                names = {a.get("en", ""), self.en_aug.get(aid, ""), self.vn_aug.get(aid, "")}
                names.update(OCR_ALIASES.get(aid, []))
                for n in names:
                    k = ocr_norm(n)
                    if len(k) < 3:
                        continue
                    prev = exact.get(k)
                    if prev is None or (self.augs[prev].get("g") or 0) < (a.get("g") or 0):
                        exact[k] = aid
                    fuzzy.append((aid, k, a.get("rarity")))
            self._ocr_index = (exact, fuzzy)
        return self._ocr_index

    def match_offer(self, lines: list, fw: int, fh: int, exclude: list | None = None):
        return match_offer(lines, fw, fh, self.ocr_index(), exclude or [])

    def _rebuild_index(self):
        self._ocr_index = None
        self._aug_index = []
        for aid, a in self.augs.items():
            keys = {norm(a.get("en", "")), norm(self.vn_aug.get(aid, ""))}
            keys.discard("")
            self._aug_index.append((aid, " | ".join(sorted(keys)), sorted(keys)))
        self._champ_index = []
        for cid, c in self.champs.items():
            keys = {norm(c.get("en", "")), norm(c.get("alias", "")), norm(self.vn_champ.get(cid, ""))}
            keys.discard("")
            self._champ_index.append((cid, " | ".join(sorted(keys)), sorted(keys)))

    @staticmethod
    def _match_rank(q: str, toks: list, blob: str, keys: list):
        if not all(t in blob for t in toks):
            return None
        if any(k.startswith(q) for k in keys):
            return 0
        words = blob.replace("|", " ").split()
        if all(any(w.startswith(t) for w in words) for t in toks):
            return 1
        return 2

    def search_augs(self, query: str, rarity: str | None = None, cid: int | None = None,
                    exclude=(), limit: int = 8) -> list[int]:
        q = norm(query)
        if not q:
            return []
        toks = q.split()
        pool = self.champ_pool(cid) if cid else {}
        out = []
        for aid, blob, keys in self._aug_index:
            if aid in exclude:
                continue
            if rarity and self.augs[aid].get("rarity") != rarity:
                continue
            r = self._match_rank(q, toks, blob, keys)
            if r is None:
                continue
            in_pool = 0 if (not pool or aid in pool) else 1
            out.append((r, in_pool, -(self.augs[aid].get("g") or 0), aid))
        out.sort()
        return [x[-1] for x in out[:limit]]

    def search_champs(self, query: str, limit: int = 8) -> list[int]:
        q = norm(query)
        if not q:
            return []
        toks = q.split()
        out = []
        for cid, blob, keys in self._champ_index:
            r = self._match_rank(q, toks, blob, keys)
            if r is not None:
                out.append((r, self.champ_name(cid), cid))
        out.sort()
        return [x[-1] for x in out[:limit]]

    def cid_from_alias(self, alias: str | None) -> int | None:
        if not alias:
            return None
        return self.alias_to_cid.get(alias_key(alias))

    # ------------------------------------------------------------- champion profile
    def _pct(self, key: str, val) -> float:
        if val is None:
            return 0.5
        arr = self._pct_cache.get(key)
        if arr is None:
            arr = sorted((c.get("comp") or {}).get(key, 0) for c in self.champs.values())
            self._pct_cache[key] = arr
        if not arr:
            return 0.5
        lo = sum(1 for x in arr if x < val)
        eq = sum(1 for x in arr if x == val)
        return (lo + 0.5 * eq) / len(arr)

    def champ_weights(self, cid: int | None, live: dict | None = None) -> dict:
        if cid is None or cid not in self.champs:
            return {}
        c = self.champs[cid]
        comp = c.get("comp") or {}
        phys, magic, true = comp.get("phys", 0), comp.get("magic", 0), comp.get("true", 0)
        tot = (phys + magic + true) or 1.0
        ps, ms = phys / tot, magic / tot
        tags = set(c.get("tags") or [])
        mk = "Marksman" in tags
        bruiser = bool(tags & {"Fighter", "Assassin"})
        w = {
            "AD": 2 * (ps - 0.5), "AP": 2 * (ms - 0.5),
            "AS": 0.9 if mk else (0.3 if ps > 0.6 and bruiser else -0.4),
            "CRIT": 0.9 if mk else (0.2 if ps > 0.7 and bruiser else -0.5),
            "SPELL": 0.7 if "Mage" in tags else (0.4 if ms > 0.5 else 0.1),
            "TANK": 1.4 * self._pct("front", comp.get("front")) - 0.5,
            "CC": 1.2 * self._pct("cc", comp.get("cc")) - 0.5,
            "VAMP": 0.4 if (bruiser or mk) else 0.0,
            "RANGE": 0.8 if mk else -0.3,
            "MS": 0.1,
        }
        w["ONHIT"] = w["AS"]
        w["HP"] = w["TANK"]
        sus = self._pct("sustain", comp.get("sustain"))
        w["HEAL"] = (0.3 + 0.9 * sus) if "Support" in tags else (-0.7 + 0.4 * sus)
        rng = None
        if live and live.get("attack_range"):
            rng = float(live["attack_range"])
        elif cid in self.champ_range:
            rng = self.champ_range[cid]
        if rng is not None:
            if rng < 300:
                w["RANGE"] = -1.2
                w["MELEE"] = 0.5
            else:
                w["MELEE"] = -0.8
        res = (live or {}).get("resource")
        if res:
            w["MANA"] = 0.6 if str(res).upper() == "MANA" else -1.5
        return w

    def axis_fit(self, aid: int, w: dict) -> float:
        if not w:
            return 0.0
        t = self.tags.get(aid) or {}
        s = sum(v * w.get(k, 0.0) for k, v in t.items())
        return max(-3.0, min(2.0, 1.2 * s))

    # ------------------------------------------------------------- scoring parts
    def champ_component(self, cid: int | None, aid: int, slot: int | None, w: dict, reasons: list | None):
        a = self.augs.get(aid) or {}
        glift = (a.get("lift") or 0.0) * 100
        fit = self.axis_fit(aid, w)
        prior = 0.5 * glift + fit
        champ = self.champs.get(cid) if cid is not None else None
        name = self.champ_name(cid)
        if not champ:
            if reasons is not None:
                reasons.append(Reason("+" if glift > 0.5 else "-" if glift < -0.5 else "i",
                                      f"Chưa chọn tướng — thống kê chung: {glift:+.1f}% tỉ lệ thắng"))
            return glift, a.get("g") or 0
        base = champ.get("wr") or 0.5
        rec = self.champ_pool(cid).get(aid)
        K = self.K_SHRINK
        games = 0
        if rec and rec[1] is not None:
            g, wr = rec
            games = g
            emp = (wr - base) * 100
            est = (g * emp + K * prior) / (g + K)
            if reasons is not None:
                if g >= 150:
                    kind = "+" if emp > 0.7 else "-" if emp < -0.7 else "i"
                    reasons.append(Reason(kind, f"Với {name}: thắng {wr * 100:.1f}% "
                                                f"({emp:+.1f}% so với TB tướng, {fmt_games(g)} trận)",
                                          f"thắng {wr * 100:.0f}% ({emp:+.1f})"))
                elif g >= 60:
                    reasons.append(Reason("i", f"Với {name}: thắng {wr * 100:.1f}% nhưng mới {g} trận — chưa chắc",
                                          "ít dữ liệu"))
                else:
                    reasons.append(Reason("i", f"Ít dữ liệu với {name} ({g} trận) — ước tính theo kiểu tướng"))
        else:
            est = prior
            if reasons is not None:
                reasons.append(Reason("i", f"Chưa có số liệu với {name} — ước tính theo kiểu tướng: {prior:+.1f}"))
        sl = self.champ_slots(cid).get(aid) if slot is not None else None
        if sl and slot is not None and slot < len(sl):
            sg, swr = sl[slot]
            if sg and swr is not None and sg >= 150:
                emp_s = (swr - base) * 100
                est_s = (sg * emp_s + K * est) / (sg + K)
                if reasons is not None and abs(est_s - est) >= 0.8:
                    reasons.append(Reason("+" if est_s > est else "-",  # noqa
                                          f"Ở lượt chọn thứ {slot + 1}: thắng {swr * 100:.1f}% ({fmt_games(sg)} trận)"))
                est = 0.5 * est + 0.5 * est_s
        return max(-9.0, min(9.0, est)), games

    def pair(self, a: int, b: int):
        """(diem, giai thich, la_combo_cu_the)"""
        rule = PAIR_RULES.get((a, b))
        if rule:
            return rule[0], rule[1], True
        ta, tb = self.tags.get(a) or {}, self.tags.get(b) or {}
        raw = 0.0
        best = (0.0, None, None)
        for ka, va in ta.items():
            for kb, vb in tb.items():
                m = AXIS_SYN.get((ka, kb))
                if m:
                    contrib = va * vb * m
                    raw += contrib
                    if abs(contrib) > abs(best[0]):
                        best = (contrib, ka, kb)
        if raw == 0:
            return 0.0, "", False
        val = 2.0 * math.tanh(raw / 1.2)
        _, ka, kb = best
        if val > 0:
            if ka == kb:
                txt = f"cùng hướng {AXIS_VN.get(ka, ka)}"
            else:
                txt = f"{AXIS_VN.get(ka, ka)} + {AXIS_VN.get(kb, kb)}"
        else:
            txt = f"{AXIS_VN.get(ka, ka)} ngược với {AXIS_VN.get(kb, kb)}"
        return val, txt, False

    def synergy_component(self, aid: int, owned: list[int], reasons: list | None):
        pos, neg = 0.0, 0.0
        lines = []
        for o in owned:
            if o == aid:
                continue
            v, txt, explicit = self.pair(o, aid)
            if v > 0:
                pos += v
            else:
                neg += v
            if reasons is not None and (abs(v) >= 0.8 or (explicit and v != 0)):
                if v > 0:
                    lines.append((v, Reason("+", f"Combo với {self.aug_name(o)}: {txt}", f"combo {self.aug_name(o)}")))
                else:
                    lines.append((v, Reason("-", f"Xung đột với {self.aug_name(o)}: {txt}",
                                            f"xung đột {self.aug_name(o)}")))
        if aid == 12317 and owned:
            pen = -0.9 * len(owned)
            neg += pen
            lines.append((pen, Reason("-", "Biến toàn bộ augment đã có thành Kim Cương ngẫu nhiên → phá combo đang có",
                                      "phá combo")))
        total = 7.0 * math.tanh(pos / 7.0) + neg
        if reasons is not None:
            lines.sort(key=lambda x: -abs(x[0]))
            reasons.extend(r for _, r in lines[:4])
        return total

    def timing_component(self, aid: int, slot: int, reasons: list | None):
        t = 0.0
        note = None
        if aid in PURE_ECON_IDS:
            if slot >= 3:
                t, note = -1.0, Reason("-", "Augment kinh tế ở lượt cuối: ít thời gian để tiêu", "kinh tế muộn")
            elif slot <= 1:
                t, note = 0.4, Reason("i", "Augment kinh tế: lấy sớm thì lời nhất", "kinh tế, lấy sớm")
        elif aid in QUEST_IDS:
            if slot >= 3:
                t, note = -1.0, Reason("-", "Nhiệm vụ cần thời gian, lượt cuối khó kịp hoàn thành", "nhiệm vụ muộn")
            elif slot == 0:
                t = 0.2
        elif aid == 1402 and slot >= 3:
            t, note = -0.5, Reason("-", "Lượt reroll thêm không còn dùng được")
        if aid in (1390, 1375) and slot == 1:
            t, note = 0.5, Reason("+", "Lấy làm augment thứ 2 được cộng thêm chỉ số khởi điểm", "lượt 2 có thưởng")
        if aid in RANDOM_IDS and aid != 12317:
            note = note or Reason("i", "Kết quả ngẫu nhiên, không tính combo được", "ngẫu nhiên")
        if reasons is not None and note:
            reasons.append(note)
        return t

    # ------------------------------------------------------------- public API
    def score(self, cid: int | None, aid: int, owned: list[int], live: dict | None = None,
              slot: int | None = None, with_reasons: bool = True) -> Scored:
        if slot is None:
            slot = min(len(owned), 3)
        w = self.champ_weights(cid, live)
        reasons: list | None = [] if with_reasons else None
        champ_v, games = self.champ_component(cid, aid, slot, w, reasons)
        syn = self.synergy_component(aid, owned, reasons)
        tim = self.timing_component(aid, slot, reasons)
        total = champ_v + syn + tim
        return Scored(aid, total, champ_v, syn, tim, reasons or [], grade_of(total), games)

    def rank_offers(self, cid, offers: list[int], owned: list[int], live=None, slot=None) -> list[Scored]:
        res = [self.score(cid, a, owned, live, slot) for a in offers if a in self.augs]
        res.sort(key=lambda s: -s.total)
        return res

    def build_direction(self, owned: list[int], top: int = 3) -> list[str]:
        acc: dict = {}
        for o in owned:
            for k, v in (self.tags.get(o) or {}).items():
                if k in ("GOLD", "ABIL"):
                    continue
                acc[k] = acc.get(k, 0) + v
        best = sorted(acc.items(), key=lambda kv: -kv[1])[:top]
        return [AXIS_VN.get(k, k) for k, v in best if v >= 0.6]

    def _candidates(self, cid, owned, min_games=120):
        pool = self.champ_pool(cid) if cid is not None else {}
        if pool:
            ids = [a for a, (g, _wr) in pool.items() if g >= min_games and a in self.augs]
        else:
            ids = [a for a, x in self.augs.items() if (x.get("g") or 0) >= 5000]
        return [a for a in ids if a not in owned and a not in RANDOM_IDS]

    def targets_by_rarity(self, cid, owned: list[int], live=None, per=3) -> dict:
        slot = min(len(owned), 3)
        out = {}
        scored = [self.score(cid, a, owned, live, slot, with_reasons=False) for a in self._candidates(cid, owned)]
        for r in RARITY_ORDER:
            rs = [s for s in scored if self.augs[s.aid].get("rarity") == r]
            rs.sort(key=lambda s: -s.total)
            out[r] = rs[:per]
        return out

    def plan_combos(self, cid, owned: list[int], live=None, n_combos=3, size=4, beam=80) -> list[tuple]:
        """Tim bo 4 augment manh nhat (giu cac augment da co)."""
        owned = list(owned)[:size]
        need = size - len(owned)
        if need <= 0:
            return [(self._set_value(cid, owned, owned, live), owned)]
        w = self.champ_weights(cid, live)
        cands = self._candidates(cid, owned)
        base_val = {a: self.champ_component(cid, a, None, w, None)[0] for a in cands}
        cands = sorted(cands, key=lambda a: -base_val[a])[:45]
        owned_pos = owned_neg = 0.0
        for i, a in enumerate(owned):
            for b in owned[i + 1:]:
                v = self.pair(a, b)[0]
                owned_pos, owned_neg = (owned_pos + v, owned_neg) if v > 0 else (owned_pos, owned_neg + v)
        # state: (chosen, sum_est, pos_syn, neg_syn); gia tri = est + 9*tanh(pos/9) + neg (cong huong giam dan)
        states = [(tuple(), 0.0, owned_pos, owned_neg)]

        def value(st):
            return st[1] + 9.0 * math.tanh(st[2] / 9.0) + st[3]

        for _ in range(need):
            nxt = {}
            for chosen, est, pos, neg in states:
                cur = list(owned) + list(chosen)
                for a in cands:
                    if a in chosen:
                        continue
                    key = tuple(sorted(chosen + (a,)))
                    if key in nxt:
                        continue
                    p = n = 0.0
                    for o in cur:
                        v = self.pair(o, a)[0]
                        if v > 0:
                            p += v
                        else:
                            n += v
                    nxt[key] = (key, est + base_val[a], pos + p, neg + n)
            states = sorted(nxt.values(), key=lambda st: -value(st))[:beam]
        out = []
        for st in states:
            k = st[0]
            if all(len(set(k) ^ set(prev)) >= 4 for _, prev in out):
                out.append((value(st), list(k)))
            if len(out) >= n_combos:
                break
        return [(v, owned + k) for v, k in out]

    def _set_value(self, cid, all_ids, owned, live):
        w = self.champ_weights(cid, live)
        v = sum(self.champ_component(cid, a, None, w, None)[0] for a in all_ids if a not in owned)
        for i, a in enumerate(all_ids):
            for b in all_ids[i + 1:]:
                v += self.pair(a, b)[0]
        return v


# --------------------------------------------------------------------------- live client

def parse_live(js: dict) -> dict:
    """Doc du lieu tu Live Client Data API (https://127.0.0.1:2999/liveclientdata/allgamedata)."""
    ap = js.get("activePlayer") or {}
    players = js.get("allPlayers") or []
    keys = [ap.get("riotId"), ap.get("summonerName")]
    gname = ap.get("riotIdGameName")
    me = None
    for p in players:
        if (p.get("riotId") and p.get("riotId") in keys) or (p.get("summonerName") and p.get("summonerName") in keys) \
                or (gname and p.get("riotIdGameName") == gname):
            me = p
            break
    me = me or {}
    raw = me.get("rawChampionName") or ""
    alias = raw.rsplit("_", 1)[-1] if raw else None
    stats = ap.get("championStats") or {}
    gd = js.get("gameData") or {}
    team = me.get("team")
    return {
        "alias": alias,
        "champ_local": me.get("championName"),
        "level": ap.get("level") or me.get("level"),
        "game_time": gd.get("gameTime"),
        "mode": gd.get("gameMode"),
        "attack_range": stats.get("attackRange"),
        "resource": stats.get("resourceType"),
        "is_dead": me.get("isDead"),
        "allies": [p.get("rawChampionName", "").rsplit("_", 1)[-1] for p in players if p.get("team") == team and p is not me],
        "enemies": [p.get("rawChampionName", "").rsplit("_", 1)[-1] for p in players if team and p.get("team") != team],
        "augment_hints": _find_augment_fields(me) + _find_augment_fields(ap),
    }


def _find_augment_fields(obj, depth=0) -> list:
    """Neu Riot co tra ve augment trong API (chua chac), lay id/ten ra."""
    found = []
    if depth > 4:
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "augment" in str(k).lower():
                found.extend(_flatten_aug(v))
            elif isinstance(v, (dict, list)):
                found.extend(_find_augment_fields(v, depth + 1))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_find_augment_fields(v, depth + 1))
    return found


def _flatten_aug(v) -> list:
    out = []
    if isinstance(v, (int, str)):
        out.append(v)
    elif isinstance(v, dict):
        for k in ("id", "augmentId", "displayName", "name", "rawDisplayName"):
            if k in v:
                out.append(v[k])
                break
    elif isinstance(v, list):
        for x in v:
            out.extend(_flatten_aug(x))
    return out


# --------------------------------------------------------------------------- OCR matching
# Ten tren the trong game doi khi khac du lieu (vd 1067 van hien ten cu "Rabble Rousing").
OCR_ALIASES = {1067: ["Rabble Rousing"]}


def ocr_norm(s: str) -> str:
    s = norm(s)
    s = re.sub(r"^(quest|nhiem vu)\s+", "", s)
    return s.replace(" ", "")


def _lev(a: str, b: str, maxd: int) -> int:
    """Khoang cach Levenshtein, dung som khi vuot maxd."""
    la, lb = len(a), len(b)
    if abs(la - lb) > maxd:
        return maxd + 1
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        ca = a[i - 1]
        cur = [i] + [0] * lb
        best = i
        for j in range(1, lb + 1):
            v = prev[j] + 1
            t = cur[j - 1] + 1
            if t < v:
                v = t
            t = prev[j - 1] + (ca != b[j - 1])
            if t < v:
                v = t
            cur[j] = v
            if v < best:
                best = v
        if best > maxd:
            return maxd + 1
        prev = cur
    return prev[lb]


def name_score(a: str, b: str, min_score: float = 0.75) -> float:
    if a == b:
        return 1.0
    m = max(len(a), len(b))
    maxd = int(m * (1 - min_score))
    d = _lev(a, b, maxd)
    return 0.0 if d > maxd else 1.0 - d / m


def _best_name(text: str, index, min_score: float, rarity: str | None = None):
    exact, fuzzy = index
    k = ocr_norm(text)
    if len(k) < 3:
        return None
    aid = exact.get(k)
    if aid is not None and rarity is None:
        return (1.0, aid)
    best = None
    for aid2, name, rar in fuzzy:
        if rarity and rar != rarity:
            continue
        if abs(len(name) - len(k)) > max(2, int(len(name) * 0.3)):
            continue
        s = name_score(k, name, min_score)
        if s >= min_score and (best is None or s > best[0] or (s == best[0] and len(name) > best[2])):
            best = (s, aid2, len(name))
    return (best[0], best[1]) if best else None


def match_offer(lines: list, fw: int, fh: int, index, exclude: list | None = None, min_score: float = 0.8):
    """Dong chu OCR (toa do theo khung game) -> 3 augment theo vi tri trai/giua/phai.

    lines: [{t|text, x, y, w, h}]. Tra ve None neu khong thay bang chon augment (< 2 the khop).
    """
    if not fw or not fh or not lines:
        return None
    exclude = exclude or []
    cands = []
    for l in lines:
        text = l.get("t") if "t" in l else l.get("text", "")
        x, y, w, h = (float(l.get(k, 0)) for k in ("x", "y", "w", "h"))
        cx, cy = x + w / 2, y + h / 2
        if not (0.08 * fw <= cx <= 0.92 * fw and 0.18 * fh <= cy <= 0.78 * fh):
            continue
        if not (0.008 * fh <= h <= 0.05 * fh) or len(ocr_norm(text or "")) < 3:
            continue
        if any(ex[0] <= cx <= ex[0] + ex[2] and ex[1] <= cy <= ex[1] + ex[3] for ex in exclude):
            continue
        cands.append({"t": text, "cx": cx, "cy": cy, "h": h, "x": x, "y": y})
    if not cands:
        return None
    radius = 0.12 * fh  # cac the cach nhau ~0.34*H
    clusters: list = []
    for c in sorted(cands, key=lambda c: c["cx"]):
        for k in clusters:
            if abs(k["cx"] - c["cx"]) <= radius:
                k["lines"].append(c)
                k["cx"] = sum(z["cx"] for z in k["lines"]) / len(k["lines"])
                break
        else:
            clusters.append({"cx": c["cx"], "lines": [c]})

    def texts_of(cl):
        ls = sorted(cl["lines"], key=lambda z: z["cy"])
        out = []
        for i, z in enumerate(ls):
            out.append((z["t"], z["cy"]))
            if i + 1 < len(ls) and ls[i + 1]["cy"] - z["cy"] < 1.9 * max(z["h"], ls[i + 1]["h"]):
                out.append((f"{z['t']} {ls[i + 1]['t']}", z["cy"]))  # ten dai bi xuong dong
        return out

    found = []
    for cl in clusters:
        best = None
        for t, cy in texts_of(cl):
            m = _best_name(t, index, min_score)
            if m and (best is None or m[0] > best[0]):
                best = (m[0], m[1], t, cy)
        cl["best"] = best
        if best:
            found.append(cl)
    if len(found) < 2:
        return None
    # Uu tien cac the co tieu de cung hang ngang.
    found.sort(key=lambda cl: -cl["best"][0])
    ref_cy = found[0]["best"][3]
    found = [cl for cl in found if abs(cl["best"][3] - ref_cy) <= 0.08 * fh]
    found = found[:3]
    if len(found) < 2:
        return None
    # Do hiem chung -> thu lai cot chua khop voi nguong thap hon.
    exact, fuzzy = index
    rar_of = {aid: r for aid, _n, r in fuzzy}
    rars = [rar_of.get(cl["best"][1]) for cl in found]
    major = max(set(rars), key=rars.count) if rars else None
    if len(found) == 2 and major and rars.count(major) == 2:
        for cl in clusters:
            if cl in found or abs(cl["cx"] - found[0]["cx"]) < radius or abs(cl["cx"] - found[1]["cx"]) < radius:
                continue
            best = None
            for t, cy in texts_of(cl):
                if abs(cy - ref_cy) > 0.08 * fh:
                    continue
                m = _best_name(t, index, 0.65, rarity=major)
                if m and (best is None or m[0] > best[0]):
                    best = (m[0], m[1], t, cy)
            if best:
                cl["best"] = best
                found.append(cl)
                break
    found.sort(key=lambda cl: cl["cx"])
    slots: list = [None, None, None]
    scores: list = [0.0, 0.0, 0.0]
    texts: list = ["", "", ""]
    pos: list = [None, None, None]  # (cx, cy) cua tieu de the, toa do theo khung game
    if len(found) == 3:
        order = [0, 1, 2]
    else:
        order = []
        for cl in found:
            col = round((cl["cx"] - fw / 2) / (0.34 * fh))
            idx = max(-1, min(1, col)) + 1
            while idx in order and idx < 2:
                idx += 1
            order.append(idx)
    seen = set()
    for idx, cl in zip(order, found):
        s, aid, t, cy = cl["best"]
        if aid in seen:
            continue
        seen.add(aid)
        slots[idx], scores[idx], texts[idx] = aid, round(s, 3), t
        pos[idx] = (int(cl["cx"]), int(cy))
    n = sum(1 for a in slots if a is not None)
    if n < 2:
        return None
    return {"slots": slots, "scores": scores, "texts": texts, "n": n, "pos": pos}
