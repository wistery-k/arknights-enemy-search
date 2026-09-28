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
    excel/crisis_table.json           危機契約（旧形式）の開催日
    excel/crisis_v2_table.json        危機契約の開催日
    excel/campaign_table.json         殲滅作戦（ローテーションマップ）の開放日
    excel/handbook_info_table.json    逆理演算のステージと追加日
    excel/character_table.json        オペレーター名（逆理演算の表示用）
    data/debut_overrides.json         初登場の手動指定（自動判定できないもの）
    levels/enemydata/enemy_database.json  ステータス・種族・移動形態
    levels/**                         各ステージの敵編成

地域（勢力）はゲームデータに存在しないため data/regions.json の手動対応表から付与する。
各敵の「初登場コンテンツ」は、登場したステージのうち開始日がいちばん早いもののコンテンツ。
敵の地域は、初登場のコンテンツ（そこに地域が無ければ次に早い、地域のあるコンテンツ）の地域になる。
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
CATEGORIES = ["メインテーマ", "イベント", "統合戦略", "生息演算", "協心競技", "堅守協定", "鋒矢突破", "特殊モード", "その他"]

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

# 特殊モードのうち、独立したカテゴリとして扱うもの: (名前の正規表現, カテゴリ名, 表示名から消す接頭辞)
CONTENT_GROUPS = [
    (r"^生息演算", "生息演算", "生息演算："),
    (r"協心競技", "協心競技", ""),
    (r"^堅守協定", "堅守協定", ""),
    (r"^鋒矢突破", "鋒矢突破", ""),
]


class Contents:
    def __init__(self):
        self.items = {}  # (category, name) -> {"category", "name", "order", "label"}

    def add(self, category, name, order):
        """order は一覧の並び順"""
        label = name
        if category == "特殊モード":
            for pattern, cat, prefix in CONTENT_GROUPS:
                if re.search(pattern, name):
                    category = cat
                    label = name[len(prefix):] if prefix and name.startswith(prefix) else name
                    break
        key = (category, name)
        cur = self.items.get(key)
        if cur is None:
            self.items[key] = {"category": category, "name": name, "order": order, "label": label}
        elif order < cur["order"]:
            cur["order"] = order
        return key


# 日本版メインテーマの公開日。第8章まではゲームデータの日付（story_review_table の startShowTime）が
# ストーリー記録機能の追加日などになっていて実際の公開日と違うため、公式告知の日付で上書きする。
JST = timezone(timedelta(hours=9))
JP_LAUNCH = datetime(2020, 1, 16, 16, tzinfo=JST)
MAIN_RELEASE_JP = {
    0: JP_LAUNCH, 1: JP_LAUNCH, 2: JP_LAUNCH, 3: JP_LAUNCH, 4: JP_LAUNCH,  # 序章〜第四章はサービス開始時から
    5: datetime(2020, 2, 26, 16, tzinfo=JST),
    6: datetime(2020, 6, 30, 16, tzinfo=JST),
    7: datetime(2020, 12, 30, 16, tzinfo=JST),
    8: datetime(2021, 4, 30, 16, tzinfo=JST),
}


def main_release_ts(chapter: int, story_review):
    if chapter in MAIN_RELEASE_JP:
        return int(MAIN_RELEASE_JP[chapter].timestamp())
    ts = (story_review.get(f"main_{chapter}") or {}).get("startShowTime", -1)
    return ts if ts and ts > 0 else None


def valid_ts(ts):
    return ts if isinstance(ts, (int, float)) and ts > 0 else None


class Tables:
    """変換に使うゲームデータのテーブル一式"""

    def __init__(self, base: Path):
        self.stages = load(base, "excel/stage_table.json")["stages"]
        self.zones = load(base, "excel/zone_table.json")["zones"]
        act = load(base, "excel/activity_table.json")
        self.basic = act["basicInfo"]
        self.zone_to_act = act["zoneToActivity"]
        self.retro = load(base, "excel/retro_table.json")
        self.story_review = load(base, "excel/story_review_table.json")
        rogue = load(base, "excel/roguelike_topic_table.json")
        self.rogue_topics = rogue["topics"]
        self.rogue_details = rogue["details"]
        self.climb = load(base, "excel/climb_tower_table.json")
        sandbox = load(base, "excel/sandbox_perm_table.json")
        self.sandbox = sandbox["basicInfo"]
        # 生息演算のステージ名（levelファイルのキー -> ステージ名）
        self.sandbox_stage_names = {}
        for topics in (sandbox.get("detail") or {}).values():
            for topic in topics.values():
                for st in (topic.get("stageData") or {}).values():
                    if st.get("levelId") and st.get("name"):
                        self.sandbox_stage_names[level_key(st["levelId"])] = st["name"]
        # 逆理演算: オペレーターごとのステージと追加日
        handbook_info = load(base, "excel/handbook_info_table.json")
        self.paradox_stages = handbook_info.get("handbookStageData") or {}
        self.paradox_dates = {}
        for group in handbook_info.get("handbookStageTime") or []:
            for char_id in group.get("charSet") or []:
                self.paradox_dates.setdefault(char_id, valid_ts(group.get("timestamp")))
        chars = load(base, "excel/character_table.json")
        self.char_names = {cid: c.get("name") for cid, c in chars.items()}
        self.crisis_v1 = sorted(
            (s for s in load(base, "excel/crisis_table.json")["seasonInfo"]),
            key=lambda s: s["startTs"],
        )
        self.crisis_v2 = load(base, "excel/crisis_v2_table.json")["seasonInfoDataMap"]
        campaign = load(base, "excel/campaign_table.json")
        self.campaign_rotate = defaultdict(lambda: None)
        for r in campaign.get("campaignRotateStageOpenTimes") or []:
            cur = self.campaign_rotate[r["stageId"]]
            if cur is None or r["startTs"] < cur:
                self.campaign_rotate[r["stageId"]] = r["startTs"]

        # イベント名（復刻を除いた名前）ごとの初回開催日。復刻のステージは復刻側のイベントIDに
        # 紐づいていることがあるため、同じ名前のイベントの最も早い開始日を使う
        self.event_first = {}
        self.rerun_linked = set()  # 常設化・復刻の対象になったイベントID
        for info in (self.retro.get("retroActList") or {}).values():
            self.rerun_linked.update(info.get("linkedActId") or [])
        for info in self.basic.values():
            self._note_event(clean_event_name(info["name"]), valid_ts(info["startTime"]))
        for info in (self.retro.get("retroActList") or {}).values():
            for a in info.get("linkedActId") or []:
                if a in self.basic:
                    self._note_event(clean_event_name(info["name"]), valid_ts(self.basic[a]["startTime"]))

    def _note_event(self, name, ts):
        if ts is not None and (name not in self.event_first or ts < self.event_first[name]):
            self.event_first[name] = ts

    def act_start(self, act_id):
        """そのイベントの開催日。復刻・常設化されたイベントは初回開催日

        エイプリルフールや導灯の試練のように毎回同じ名前のイベントは、回ごとの開催日を使う
        （同じ名前の最初の回の日付にすると、後の回で追加された敵まで古い日付になってしまう）。
        """
        info = self.basic.get(act_id)
        if not info:
            return None
        if "復刻" in info["name"] or act_id in self.rerun_linked:
            return self.event_first.get(clean_event_name(info["name"]))
        return valid_ts(info["startTime"])

    def tower_start(self, tower_id):
        """その保全駐在マップが最初に開放されたシーズンの開始日（訓練マップは最初のシーズン）"""
        seasons = self.climb.get("seasonInfos") or {}
        hits = [s["startTs"] for s in seasons.values() if tower_id in (s.get("towers") or [])]
        if not hits and tower_id.startswith("tower_tr"):
            hits = [s["startTs"] for s in seasons.values()]
        return min(hits) if hits else None

    def crisis_start(self, fname):
        """危機契約のマップ名から、そのマップが使われた最初のシーズンの開始日を推定する"""
        m = re.match(r"level_crisis_v2_(\d+)-", fname)
        if m:
            info = self.crisis_v2.get(f"crisis_v2_season_{int(m.group(1))}_1")
            return valid_ts(info["startTs"]) if info else None
        m = re.match(r"level_rune_(\d+)-", fname)
        if m and self.crisis_v1:
            # rune_01 が最初のシーズン。以降おおむねシーズンごとに1マップずつ増えている
            i = min(int(m.group(1)) - 1, len(self.crisis_v1) - 1)
            return valid_ts(self.crisis_v1[i]["startTs"])
        return None


def build_level_map(t: Tables):
    """levelファイルのキー -> (contentKey, ステージコード, 開始日) の対応を作る"""
    contents = Contents()
    level_map = {}

    def put(level_id, ckey, code, date):
        if not level_id:
            return
        level_map.setdefault(level_key(level_id), (ckey, code, date))

    for sid, st in t.stages.items():
        zone = t.zones.get(st["zoneId"])
        ztype = zone["type"] if zone else None
        code = st.get("code") or sid

        if ztype == "MAINLINE":
            name = " ".join(x for x in [zone["zoneNameFirst"], zone["zoneNameSecond"]] if x)
            chapter = int(re.sub(r"\D", "", zone["zoneID"]) or 0)  # main_10 -> 10（zoneIndexは章順ではない）
            ckey = contents.add("メインテーマ", name, chapter)
            date = main_release_ts(chapter, t.story_review)
        elif ztype in ("ACTIVITY", "MAINLINE_ACTIVITY"):
            act_id = t.zone_to_act.get(st["zoneId"])
            info = t.basic.get(act_id)
            if not info:
                continue
            ckey = add_activity(contents, info)
            date = t.act_start(act_id)
        elif ztype == "CAMPAIGN":
            ckey = contents.add("特殊モード", "殲滅作戦", 30)
            date = t.campaign_rotate[sid]  # 常設マップは日付不明
        elif ztype == "WEEKLY" or st["stageType"] == "DAILY":
            ckey = contents.add("その他", "資源収集・物資調達", 10)
            date = None
        else:
            continue
        put(st.get("levelId"), ckey, code, date)

    # 常設化されたサイドストーリー・オムニバス（retro_table）
    zone_to_retro = t.retro["zoneToRetro"]
    for sid, st in (t.retro.get("stageList") or {}).items():
        retro_id = zone_to_retro.get(st["zoneId"])
        info = t.retro["retroActList"].get(retro_id)
        if not info:
            continue
        date = t.event_first.get(clean_event_name(info["name"])) or valid_ts(info["startTime"])
        ckey = contents.add("イベント", clean_event_name(info["name"]), date or 10**10)
        put(st.get("levelId"), ckey, st.get("code") or sid, date)

    # 統合戦略（ステージごとの差し替えマップ levelReplaceIds も含める）
    for i, (topic_id, topic) in enumerate(t.rogue_topics.items()):
        ckey = contents.add("統合戦略", topic["name"], i)
        date = valid_ts(topic.get("startTime"))
        for stage in t.rogue_details.get(topic_id, {}).get("stages", {}).values():
            # 統合戦略のステージコードは難易度区分(ISW-NO等)で共通なので、ステージ名を使う
            label = stage.get("name") or stage.get("code")
            put(stage.get("levelId"), ckey, label, date)
            replace = stage.get("levelReplaceIds") or []
            if isinstance(replace, dict):
                replace = list(replace.values())
            for rid in replace:
                for lid in (rid if isinstance(rid, list) else [rid]):
                    put(lid, ckey, label, date)

    # 保全駐在
    ckey = contents.add("特殊モード", "保全駐在", 20)
    for lv in t.climb["levels"].values():
        put(lv.get("levelId"), ckey, lv.get("code"), t.tower_start(lv.get("towerId", "")))

    # 逆理演算（ステージコードの代わりにオペレーター名を表示する）
    ckey = contents.add("その他", "逆理演算", 20)
    for char_id, st in t.paradox_stages.items():
        put(st.get("levelId"), ckey, t.char_names.get(char_id) or st.get("code"), t.paradox_dates.get(char_id))

    return contents, level_map


def add_activity(contents: Contents, info):
    name = clean_event_name(info["name"])
    category = "特殊モード" if info.get("type", "").startswith(SPECIAL_ACT_TYPES) else "イベント"
    return contents.add(category, name, info["startTime"])


def classify_unmapped(key: str, contents: Contents, t: Tables):
    """テーブルから辿れなかったレベルファイルをフォルダ名で分類する: (contentKey, コード, 開始日)"""
    parts = key.split("/")
    fname = parts[-1]
    code = fname.replace("level_", "")
    if parts[:2] in (["obt", "crisis"], ["obt", "rune"], ["obt", "recalrune"]):
        return contents.add("特殊モード", "危機契約", 40), code, t.crisis_start(fname)
    if parts[:2] == ["obt", "sandbox"]:
        m = re.match(r"level_sandbox(\d+)_", fname)
        topic = t.sandbox.get(f"sandbox_{m.group(1)}") if m else None
        name = f"生息演算：{topic['topicName']}" if topic else "生息演算"
        date = valid_ts(topic.get("topicStartTime")) if topic else None
        return contents.add("特殊モード", name, 50), t.sandbox_stage_names.get(key, code), date
    if parts[:2] == ["obt", "roguelike"] and len(parts) >= 3:
        # ro4 -> rogue_4 のテーマ（テーブルに載っていない差し替えマップ等）
        m = re.match(r"ro(\d+)$", parts[2])
        topic_id = f"rogue_{m.group(1)}" if m else None
        topic = t.rogue_topics.get(topic_id)
        if topic:
            order = list(t.rogue_topics).index(topic_id)
            return contents.add("統合戦略", topic["name"], order), code, valid_ts(topic.get("startTime"))
        return None
    if parts[:2] == ["obt", "legion"]:
        return contents.add("特殊モード", "保全駐在", 20), code, None
    if parts[:2] == ["obt", "memory"]:
        return contents.add("その他", "逆理演算", 20), code, None
    if parts[0] == "activities" and len(parts) >= 3:
        info = t.basic.get(parts[1])
        if info:
            return add_activity(contents, info), code, t.act_start(parts[1])
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
# 初登場と地域
# ---------------------------------------------------------------

def appearance_key(app, content_list):
    """早い順に並べるためのキー。日付不明の登場は日付のわかるものより後ろ"""
    idx, date = app
    c = content_list[idx]
    return (date is None, date or 0, CATEGORIES.index(c["category"]), c["order"], idx)


def find_debut(dated_apps, content_list, region_by_content):
    """(初登場コンテンツ, 初登場日, 地域の配列, 地域の元になったコンテンツ) を返す

    初登場は開始日がいちばん早い登場。地域は、地域が設定されているコンテンツのうち
    いちばん早いもの（初登場が危機契約などで地域が無い場合は、次に早いものになる）。
    """
    if not dated_apps:
        return None, None, [], None
    ordered = sorted(dated_apps, key=lambda a: appearance_key(a, content_list))
    debut, debut_date = ordered[0]
    for idx, _date in ordered:
        regions = region_by_content.get(content_list[idx]["name"])
        if regions:
            return debut, debut_date, list(regions), idx
    return debut, debut_date, [], None


# 常設で後から追加ステージがあり、ステージごとの追加日がデータに無いカテゴリ。
# ここでの登場日はモード開始日で代用しているため、実際より早く見えることがある
IMPRECISE_CATEGORIES = {"統合戦略", "生息演算", "危機契約", "逆理演算"}


def index_series(index):
    """図鑑番号の記号部分（SMN16 -> SMN）。同じ記号の敵は同じイベント等で追加されたことが多い"""
    m = re.match(r"[A-Za-z]+", index or "")
    return m.group(0) if m else None


def assign_debuts(enemies, content_list, region_by_content):
    """統合戦略・生息演算などの日付の粗さを、図鑑番号の系統で補正する

    例: 「リードギター」(SMN16) は生息演算の後から追加されたステージにも出るが、
    モード開始日で比べるとバベルより早く見えてしまう。SMN の敵の大半はバベルが初登場なので、
    バベルにも出ている SMN の敵は、生息演算での登場日をバベルでの登場日より後ろに回す。
    """
    def is_imprecise(idx):
        c = content_list[idx]
        return c["category"] in IMPRECISE_CATEGORIES or c["name"] in IMPRECISE_CATEGORIES

    # 1回目: そのまま初登場を出し、系統ごとに最も多い初登場コンテンツを「系統の出どころ」とする
    votes = defaultdict(lambda: defaultdict(int))
    for e in enemies:
        series = index_series(e["index"])
        debut = find_debut(e["_dated"], content_list, region_by_content)[0]
        if series and debut is not None:
            votes[series][debut] += 1
    origin = {}
    for series, counts in votes.items():
        best = max(counts.items(), key=lambda kv: kv[1])
        # 系統の過半数がそこで初登場している場合だけ採用する（拮抗しているときは補正しない）
        if not is_imprecise(best[0]) and best[1] >= 2 and best[1] * 2 > sum(counts.values()):
            origin[series] = best[0]

    # 2回目: 出どころにも出ている敵は、日付の粗いコンテンツでの登場日を出どころより後ろにする
    for e in enemies:
        src = origin.get(index_series(e["index"]))
        if src is None:
            continue
        push_after(e, src, is_imprecise)

    # 3回目: 図鑑番号の並び（おおむね追加順）で前後にいる敵を見る。
    # 初登場が日付の粗いコンテンツになっている敵で、前後の敵の多くが初登場したコンテンツに
    # その敵も出ているなら、そちらを初登場とする（例: 墟の敵の間に挟まった統合戦略初登場の敵）
    debuts = [find_debut(e["_dated"], content_list, region_by_content)[0] for e in enemies]
    for i, e in enumerate(enemies):
        if debuts[i] is None or not is_imprecise(debuts[i]):
            continue
        appears = {idx for idx, _d in e["_dated"]}
        near = [debuts[j] for j in range(max(0, i - NEIGHBOR_WINDOW), min(len(enemies), i + NEIGHBOR_WINDOW + 1))
                if j != i and debuts[j] is not None and not is_imprecise(debuts[j]) and debuts[j] in appears]
        if not near:
            continue
        src, n = max(((c, near.count(c)) for c in set(near)), key=lambda kv: kv[1])
        if n >= 2:
            push_after(e, src, is_imprecise)


NEIGHBOR_WINDOW = 4


def push_after(e, src, is_imprecise):
    """日付の粗いコンテンツでの登場日を、src での登場日より後ろにする"""
    dates = dict(e["_dated"])
    if dates.get(src) is None:
        return
    e["_dated"] = [
        (idx, (dates[src] + 1) if is_imprecise(idx) and (d is None or d <= dates[src]) else d)
        for idx, d in e["_dated"]
    ]


def fill_debut_from_series(enemies, content_list, region_by_content, content_first):
    """どのステージにも出てこない敵（生息演算のフィールドにだけ出る敵など）は、
    図鑑番号の系統の過半数が初登場したコンテンツを初登場とする"""
    votes = defaultdict(lambda: defaultdict(int))
    for e in enemies:
        series = index_series(e["index"])
        if series and e["debut"] is not None:
            votes[series][e["debut"]] += 1
    for e in enemies:
        counts = votes.get(index_series(e["index"]))
        if e["debut"] is not None or not counts:
            continue
        best, n = max(counts.items(), key=lambda kv: kv[1])
        if n * 2 <= sum(counts.values()):
            continue
        e["debut"], e["debutAt"] = best, content_first.get(best)
        e["appear"] = sorted(e["appear"] + [[best, []]], key=lambda a: a[0])
        regions = region_by_content.get(content_list[best]["name"], [])
        e["regions"], e["regionFrom"] = list(regions), (best if regions else None)


def apply_debut_overrides(enemies, content_list, contents, t, region_by_content, content_first):
    """data/debut_overrides.json の手動指定で初登場を上書きする

    ステージデータが残っていないコラボイベントなど、自動では判定できないもの用。
    """
    path = ROOT / "data" / "debut_overrides.json"
    if not path.exists():
        return
    cfg = json.loads(path.read_text(encoding="utf-8"))

    # 追加のコンテンツ（ゲームデータにステージが残っていないイベントなど）
    extra_dates = {}
    for c in cfg.get("contents") or []:
        info = t.basic.get(c.get("activity")) or {}
        date = valid_ts(info.get("startTime"))
        key = contents.add(c["category"], c["name"], date or 10**10)
        if key not in [(x["category"], x["name"]) for x in content_list]:
            content_list.append(contents.items[key])
        extra_dates[c["name"]] = date
    # 追加したコンテンツも含めて並べ直し、各敵の番号を付け直す
    old = list(content_list)
    content_list.sort(key=lambda c: (CATEGORIES.index(c["category"]), c["order"], c["name"]))
    remap = {i: content_list.index(c) for i, c in enumerate(old)}
    content_first = {remap[i]: d for i, d in content_first.items()}
    for e in enemies:
        e["appear"] = sorted([[remap[i], codes] for i, codes in e["appear"]], key=lambda a: a[0])
        e["_datemap"] = {remap[i]: d for i, d in e["_datemap"].items()}
        for k in ("debut", "regionFrom"):
            if e[k] is not None:
                e[k] = remap[e[k]]

    by_name = {c["name"]: i for i, c in enumerate(content_list)}
    order = [e["index"] for e in enemies]
    by_index = {e["index"]: e for e in enemies}
    for rule in cfg.get("rules") or []:
        target = by_name.get(rule["content"])
        if target is None:
            print(f"警告: debut_overrides.json のコンテンツ「{rule['content']}」が見つかりません")
            continue
        picked = [by_index[i] for i in rule.get("indexes") or [] if i in by_index]
        if rule.get("range"):
            a, b = (order.index(x) for x in rule["range"])
            picked += enemies[a:b + 1]
        for e in picked:
            e["debut"] = target
            if not any(a[0] == target for a in e["appear"]):
                e["appear"] = sorted(e["appear"] + [[target, []]], key=lambda a: a[0])
            # 初登場日: 追加コンテンツの開催日 > その敵のそこでの登場日 > そのコンテンツの最初の日付
            e["debutAt"] = (extra_dates.get(rule["content"]) or e["_datemap"].get(target)
                            or content_first.get(target))
            # 地域: そのコンテンツの地域。地域が設定されていないコンテンツなら地域なし
            regions = rule.get("regions", region_by_content.get(rule["content"], []))
            e["regions"], e["regionFrom"] = list(regions), (target if regions else None)


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

    tables = Tables(base)
    contents, level_map = build_level_map(tables)

    # 敵ID -> {contentKey -> {"codes": set(ステージコード), "date": そのコンテンツでの最初の登場日}}
    appear = defaultdict(dict)
    unmapped = defaultdict(int)
    for path in levels_dir.rglob("level_*.json"):
        key = file_key(path, levels_dir)
        hit = level_map.get(key) or classify_unmapped(key, contents, tables)
        if not hit:
            unmapped[key.split("/")[0] + "/" + key.split("/")[1]] += 1
            continue
        ckey, code, date = hit
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for eid in enemies_in_level(data):
            rec = appear[eid].setdefault(ckey, {"codes": set(), "date": None})
            rec["codes"].add(code or "")
            if date is not None and (rec["date"] is None or date < rec["date"]):
                rec["date"] = date

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

        apps, dated = [], []
        for ckey, rec in appear.get(eid, {}).items():
            codes = sorted((c for c in rec["codes"] if c), key=natural_key)
            apps.append([content_index[ckey], codes])
            dated.append((content_index[ckey], rec["date"]))
        apps.sort(key=lambda a: a[0])

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
            "sort": hb.get("sortId", 0),
            "_dated": dated,
        })

    # 初登場と地域（図鑑番号の並びを使うので先に図鑑順に並べる）
    enemies.sort(key=lambda e: e["sort"])
    for e in enemies:
        del e["sort"]
    assign_debuts(enemies, content_list, region_by_content)
    content_first = {}
    for e in enemies:
        dated = e.pop("_dated")
        e["_datemap"] = dict(dated)
        for idx, d in dated:
            if d is not None and (idx not in content_first or d < content_first[idx]):
                content_first[idx] = d
        e["debut"], e["debutAt"], e["regions"], e["regionFrom"] = find_debut(dated, content_list, region_by_content)
    fill_debut_from_series(enemies, content_list, region_by_content, content_first)
    apply_debut_overrides(enemies, content_list, contents, tables, region_by_content, content_first)
    for e in enemies:
        del e["_datemap"]
    for e in enemies:
        if e["id"] in region_by_enemy:  # 地域は個別指定を優先
            e["regions"], e["regionFrom"] = region_by_enemy[e["id"]], None

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
        "contents": [
            {k: x for k, x in (("category", c["category"]), ("name", c["name"]),
                               ("label", c["label"] if c["label"] != c["name"] else None))
             if x is not None}
            for c in content_list
        ],
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
