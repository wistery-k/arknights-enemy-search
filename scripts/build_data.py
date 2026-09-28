#!/usr/bin/env python3
"""
ゲームデータ（ArknightsAssets/ArknightsGamedata の jp/gamedata）から
data/enemies.json を生成する。

使い方:
    python3 scripts/build_data.py <gamedataディレクトリ> [出力先]

例:
    python3 scripts/build_data.py ../ArknightsGamedata/jp/gamedata data/enemies.json

必要なファイル:
    excel/enemy_handbook_table.json   敵図鑑（名前・ランク・説明・能力）
    excel/stage_table.json            ステージ → レベルファイル、ゾーン
    excel/zone_table.json             ゾーン名（メインテーマの章名など）
    excel/activity_table.json         イベント名・開催日
    excel/retro_table.json            常設化されたサイドストーリー/オムニバス
    excel/roguelike_topic_table.json  統合戦略
    excel/climb_tower_table.json      保全駐在
    excel/sandbox_perm_table.json     生息演算
    excel/story_review_table.json     メインテーマの公開日
    levels/enemydata/enemy_database.json  ステータス・種族・移動形態
    levels/**                         各ステージの敵編成

地域（勢力）はゲームデータに存在しないため data/regions.json の手動対応表から付与する。
敵の地域は、その敵が初登場したコンテンツ（地域が設定されているもの）の地域になる。
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RANK = {"NORMAL": "通常", "ELITE": "エリート", "BOSS": "ボス"}
DAMAGE = {"PHYSIC": "物理", "MAGIC": "術", "NO_DAMAGE": "攻撃しない", "HEAL": "回復"}
MOTION = {"WALK": "地上", "FLY": "空中"}
APPLY_WAY = {"MELEE": "近距離", "RANGED": "遠距離", "ALL": "近/遠", "NONE": "攻撃しない"}

# カテゴリの表示順
CATEGORIES = ["メインテーマ", "イベント", "統合戦略", "特殊モード", "その他"]

# イベント扱いではなく「特殊モード」に分類する activity_table の type（前方一致）
SPECIAL_ACT_TYPES = ("BOSS_RUSH", "VEC_BREAK", "MULTIPLAY", "AUTOCHESS", "ENEMY_DUEL", "ARCADE", "HALFIDLE")


def clean_event_name(name: str) -> str:
    """復刻と初回開催を同じイベントにまとめる"""
    name = name.replace("·", "・")
    return re.sub(r"・?復刻$", "", name).strip()


def natural_key(s: str):
    """1-2 < 1-10 になるよう数字部分を数値として比較する"""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", s)]


def load(base: Path, rel: str):
    with open(base / rel, encoding="utf-8") as f:
        return json.load(f)


def level_key(level_id: str) -> str:
    """stage_table の levelId (例: Obt/Main/level_main_01-07) をファイルパスと同じ小文字キーにする"""
    return level_id.replace("\\", "/").lower().strip("/")


def file_key(path: Path, levels_dir: Path) -> str:
    return path.relative_to(levels_dir).with_suffix("").as_posix().lower()


# ---------------------------------------------------------------
# コンテンツ（どのモード・どのイベントか）の登録
# ---------------------------------------------------------------

class Contents:
    def __init__(self):
        self.items = {}  # (category, name) -> {"category", "name", "order", "date"}

    def add(self, category, name, order, date=None):
        """order は一覧の並び順、date は開始日（UNIX秒。初登場の判定に使う。不明なら None）"""
        key = (category, name)
        cur = self.items.get(key)
        if cur is None:
            self.items[key] = {"category": category, "name": name, "order": order, "date": date}
        else:
            if order < cur["order"]:
                cur["order"] = order
            if date is not None and (cur["date"] is None or date < cur["date"]):
                cur["date"] = date
        return key


# 日本版メインテーマの公開日。第8章まではゲームデータの日付（story_review_table の startShowTime）が
# ストーリー記録機能の追加日などになっていて実際の公開日と違うため、公式告知の日付で上書きする。
JST = timezone(timedelta(hours=9))
MAIN_RELEASE_JP = {
    0: datetime(2020, 1, 16, 16, tzinfo=JST),   # 序章〜第四章はサービス開始時から
    1: datetime(2020, 1, 16, 16, tzinfo=JST),
    2: datetime(2020, 1, 16, 16, tzinfo=JST),
    3: datetime(2020, 1, 16, 16, tzinfo=JST),
    4: datetime(2020, 1, 16, 16, tzinfo=JST),
    5: datetime(2020, 2, 26, 16, tzinfo=JST),
    6: datetime(2020, 6, 30, 16, tzinfo=JST),
    7: datetime(2020, 12, 30, 16, tzinfo=JST),
    8: datetime(2021, 4, 30, 16, tzinfo=JST),
}


def main_release_ts(chapter: int, story_review) -> int | None:
    if chapter in MAIN_RELEASE_JP:
        return int(MAIN_RELEASE_JP[chapter].timestamp())
    ts = (story_review.get(f"main_{chapter}") or {}).get("startShowTime", -1)
    return ts if ts and ts > 0 else None


def build_level_map(base: Path):
    """levelファイルのキー -> (contentKey, ステージコード) の対応を作る"""
    contents = Contents()
    level_map = {}

    def put(level_id, ckey, code):
        if not level_id:
            return
        level_map.setdefault(level_key(level_id), (ckey, code))

    stage_table = load(base, "excel/stage_table.json")["stages"]
    zones = load(base, "excel/zone_table.json")["zones"]
    act = load(base, "excel/activity_table.json")
    basic = act["basicInfo"]
    zone_to_act = act["zoneToActivity"]
    retro = load(base, "excel/retro_table.json")
    story_review = load(base, "excel/story_review_table.json")

    def act_order(act_id):
        info = basic.get(act_id)
        return info["startTime"] if info else 10**10

    for sid, st in stage_table.items():
        zone = zones.get(st["zoneId"])
        ztype = zone["type"] if zone else None
        code = st.get("code") or sid

        if ztype == "MAINLINE":
            name = " ".join(x for x in [zone["zoneNameFirst"], zone["zoneNameSecond"]] if x)
            chapter = int(re.sub(r"\D", "", zone["zoneID"]) or 0)  # main_10 -> 10（zoneIndexは章順ではない）
            ckey = contents.add("メインテーマ", name, chapter, main_release_ts(chapter, story_review))
        elif ztype in ("ACTIVITY", "MAINLINE_ACTIVITY"):
            act_id = zone_to_act.get(st["zoneId"])
            info = basic.get(act_id)
            if not info:
                continue
            ckey = add_activity(contents, info)
        elif ztype == "CAMPAIGN":
            ckey = contents.add("特殊モード", "殲滅作戦", 30)
        elif ztype == "WEEKLY" or st["stageType"] == "DAILY":
            ckey = contents.add("その他", "資源収集・物資調達", 10)
        else:
            continue
        put(st.get("levelId"), ckey, code)

    # 常設化されたサイドストーリー・オムニバス（retro_table）
    zone_to_retro = retro["zoneToRetro"]
    for sid, st in (retro.get("stageList") or {}).items():
        retro_id = zone_to_retro.get(st["zoneId"])
        info = retro["retroActList"].get(retro_id)
        if not info:
            continue
        linked = [a for a in (info.get("linkedActId") or []) if a in basic]
        order = min((act_order(a) for a in linked), default=info["startTime"])
        ckey = contents.add("イベント", clean_event_name(info["name"]), order, order)
        put(st.get("levelId"), ckey, st.get("code") or sid)

    # 統合戦略（ステージごとの差し替えマップ levelReplaceIds も含める）
    rogue = load(base, "excel/roguelike_topic_table.json")
    for i, (topic_id, topic) in enumerate(rogue["topics"].items()):
        ckey = contents.add("統合戦略", topic["name"], i, topic.get("startTime"))
        for stage in rogue["details"].get(topic_id, {}).get("stages", {}).values():
            # 統合戦略のステージコードは難易度区分(ISW-NO等)で共通なので、ステージ名を使う
            label = stage.get("name") or stage.get("code")
            put(stage.get("levelId"), ckey, label)
            replace = stage.get("levelReplaceIds") or []
            if isinstance(replace, dict):
                replace = list(replace.values())
            for rid in replace:
                for lid in (rid if isinstance(rid, list) else [rid]):
                    put(lid, ckey, label)

    # 保全駐在
    climb = load(base, "excel/climb_tower_table.json")
    ckey = contents.add("特殊モード", "保全駐在", 20)
    for lv in climb["levels"].values():
        put(lv.get("levelId"), ckey, lv.get("code"))

    return contents, level_map, basic, rogue["topics"]


def add_activity(contents: Contents, info):
    name = clean_event_name(info["name"])
    category = "特殊モード" if info.get("type", "").startswith(SPECIAL_ACT_TYPES) else "イベント"
    return contents.add(category, name, info["startTime"], info["startTime"])


def classify_unmapped(key: str, contents: Contents, basic, sandbox_info, rogue_topics):
    """テーブルから辿れなかったレベルファイルをフォルダ名で分類する"""
    parts = key.split("/")
    fname = parts[-1]
    if parts[:2] == ["obt", "crisis"] or parts[:2] == ["obt", "rune"] or parts[:2] == ["obt", "recalrune"]:
        return contents.add("特殊モード", "危機契約", 40), fname.replace("level_", "")
    if parts[:2] == ["obt", "sandbox"]:
        m = re.match(r"level_sandbox(\d+)_", fname)
        topic = sandbox_info.get(f"sandbox_{m.group(1)}") if m else None
        name = f"生息演算：{topic['topicName']}" if topic else "生息演算"
        date = topic.get("topicStartTime") if topic else None
        return contents.add("特殊モード", name, 50, date), fname.replace("level_", "")
    if parts[:2] == ["obt", "roguelike"] and len(parts) >= 3:
        # ro4 -> rogue_4 のテーマ（テーブルに載っていない差し替えマップ等）
        m = re.match(r"ro(\d+)$", parts[2])
        topic = rogue_topics.get(f"rogue_{m.group(1)}") if m else None
        if topic:
            order = list(rogue_topics).index(f"rogue_{m.group(1)}")
            return contents.add("統合戦略", topic["name"], order, topic.get("startTime")), fname.replace("level_", "")
        return None
    if parts[:2] == ["obt", "legion"]:
        return contents.add("特殊モード", "保全駐在", 20), fname.replace("level_", "")
    if parts[:2] == ["obt", "memory"]:
        return contents.add("その他", "オペレーター密録", 20), fname.replace("level_", "")
    if parts[0] == "activities" and len(parts) >= 3:
        info = basic.get(parts[1])
        if info:
            return add_activity(contents, info), fname.replace("level_", "")
    return None


# ---------------------------------------------------------------
# レベルファイルから敵を拾う
# ---------------------------------------------------------------

def enemies_in_level(data):
    ids = set()
    for ref in data.get("enemyDbRefs") or []:
        if ref.get("id"):
            ids.add(ref["id"])
    return ids


# ---------------------------------------------------------------
# ステータス
# ---------------------------------------------------------------

def v(field):
    return field.get("m_value") if isinstance(field, dict) and field.get("m_defined") else None


def build_stats(db_entry):
    """enemy_database の level 0 を基準に、以降のレベルは差分で上書き"""
    levels = []
    base = None
    for lv in db_entry:
        d = lv["enemyData"]
        a = d["attributes"]
        cur = {
            "hp": v(a["maxHp"]),
            "atk": v(a["atk"]),
            "def": v(a["def"]),
            "res": v(a["magicResistance"]),
            "speed": v(a["moveSpeed"]),
            "interval": v(a["baseAttackTime"]),
            "weight": v(a["massLevel"]),
            "range": v(d.get("rangeRadius", {})),
            "lifeReduce": v(d.get("lifePointReduce", {})),
        }
        if base is None:
            base = {k: (0 if x is None else x) for k, x in cur.items()}
            merged = dict(base)
        else:
            merged = {k: (x if x is not None else base[k]) for k, x in cur.items()}
        levels.append({k: (round(x, 2) if isinstance(x, float) else x) for k, x in merged.items()})
    return levels


# ---------------------------------------------------------------
# 地域
# ---------------------------------------------------------------

def debut_region(apps, content_list, region_by_content):
    """初登場のコンテンツの地域を返す: (地域の配列, そのコンテンツの番号)

    開始日がわかっていて地域が設定されているコンテンツのうち、いちばん早いものを初登場とみなす。
    本当の初登場が地域の無いコンテンツ（危機契約など）の場合は、その次に早いコンテンツの地域を使う。
    同じ日のものはメインテーマの章番号などの並び順で決める。
    """
    candidates = []
    for idx, _codes in apps:
        c = content_list[idx]
        if c["date"] is None or not region_by_content.get(c["name"]):
            continue
        candidates.append((c["date"], CATEGORIES.index(c["category"]), c["order"], idx))
    if not candidates:
        return [], None
    idx = min(candidates)[3]
    return list(region_by_content[content_list[idx]["name"]]), idx


# ---------------------------------------------------------------
# main
# ---------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    base = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "enemies.json"
    levels_dir = base / "levels"

    handbook = load(base, "excel/enemy_handbook_table.json")
    race_names = {k: r["raceName"] for k, r in handbook["raceData"].items()}
    db = load(base, "levels/enemydata/enemy_database.json")
    if isinstance(db, dict) and "enemies" in db:  # 旧形式 {"enemies": [{"Key","Value"}]}
        db = {e["Key"]: e["Value"] for e in db["enemies"]}

    sandbox = load(base, "excel/sandbox_perm_table.json")
    sandbox_info = sandbox["basicInfo"]

    contents, level_map, basic, rogue_topics = build_level_map(base)

    # 敵ID -> {contentKey -> set(ステージコード)}
    appear = defaultdict(lambda: defaultdict(set))
    unmapped = defaultdict(int)
    for path in levels_dir.rglob("level_*.json"):
        key = file_key(path, levels_dir)
        hit = level_map.get(key) or classify_unmapped(key, contents, basic, sandbox_info, rogue_topics)
        if not hit:
            unmapped[key.split("/")[0] + "/" + key.split("/")[1]] += 1
            continue
        ckey, code = hit
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for eid in enemies_in_level(data):
            appear[eid][ckey].add(code or "")

    # 地域の手動対応表
    regions_path = ROOT / "data" / "regions.json"
    regions_cfg = json.loads(regions_path.read_text(encoding="utf-8")) if regions_path.exists() else {}
    region_by_enemy = regions_cfg.get("byEnemy", {})
    region_by_content = regions_cfg.get("byContent", {})

    # コンテンツ一覧（図鑑に載っている敵が1体以上いるものだけ。カテゴリ順 → 開催順）
    visible = {eid for eid, hb in handbook["enemyData"].items() if not hb.get("hideInHandbook")}
    used_keys = {ck for eid, per in appear.items() if eid in visible for ck in per}
    content_list = sorted(
        (contents.items[k] for k in used_keys),
        key=lambda c: (CATEGORIES.index(c["category"]), c["order"], c["name"]),
    )
    content_index = {(c["category"], c["name"]): i for i, c in enumerate(content_list)}

    enemies = []
    for eid, hb in handbook["enemyData"].items():
        if hb.get("hideInHandbook"):
            continue
        entry = db.get(eid)
        base_data = entry[0]["enemyData"] if entry else {}
        tags = v(base_data.get("enemyTags", {})) or hb.get("enemyTags") or []

        apps = []
        for ckey, codes in appear.get(eid, {}).items():
            codes = sorted((c for c in codes if c), key=natural_key)
            apps.append([content_index[ckey], codes])
        apps.sort(key=lambda a: a[0])

        # 地域: 個別指定 > 初登場コンテンツの地域
        regions = region_by_enemy.get(eid)
        region_from = None
        if regions is None:
            regions, region_from = debut_region(apps, content_list, region_by_content)

        enemies.append({
            "id": eid,
            "index": hb.get("enemyIndex"),
            "name": hb["name"],
            "rank": RANK.get(hb.get("enemyLevel"), hb.get("enemyLevel")),
            "races": [race_names.get(t, t) for t in tags],
            "damage": [DAMAGE.get(d, d) for d in hb.get("damageType") or []],
            "motion": MOTION.get(v(base_data.get("motion", {})), "地上"),
            "attackRange": APPLY_WAY.get(v(base_data.get("applyWay", {})), ""),
            "abilities": [a["text"] for a in hb.get("abilityList") or []],
            "description": hb.get("description") or "",
            "stats": build_stats(entry) if entry else [],
            "appear": apps,
            "regions": regions,
            "regionFrom": region_from,
            "sort": hb.get("sortId", 0),
        })

    enemies.sort(key=lambda e: e["sort"])
    for e in enemies:
        del e["sort"]

    version = ""
    vfile = base / "excel" / "data_version.txt"
    if vfile.exists():
        m = re.search(r"VersionControl:(\S+)", vfile.read_text(encoding="utf-8"))
        version = m.group(1) if m else ""

    result = {
        "meta": {
            "source": "ArknightsAssets/ArknightsGamedata (jp)",
            "dataVersion": version,
            "categories": CATEGORIES,
        },
        "contents": [{"category": c["category"], "name": c["name"]} for c in content_list],
        "enemies": enemies,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    no_appear = sum(1 for e in enemies if not e["appear"])
    print(f"敵 {len(enemies)} 体 / コンテンツ {len(content_list)} 件 / 出力 {out} ({out.stat().st_size // 1024} KB)")
    print(f"登場先が見つからなかった敵: {no_appear} 体")
    if unmapped:
        print("分類できなかったレベルファイル（フォルダ別件数）:")
        for k, n in sorted(unmapped.items(), key=lambda x: -x[1]):
            print(f"  {k}: {n}")


if __name__ == "__main__":
    main()
