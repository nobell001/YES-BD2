from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.utils.calibration import HD_720
from src.utils.vision_models import MatchResult, TemplateSpec

__all__ = [
    "MatchResult",
    "TemplateSpec",
]

# map_trade vision coordinates are calibrated at 1280×720 and converted to
# the live client resolution at runtime.
MAP_TRADE_REFERENCE = HD_720
DAILY_ABSORB_LIMIT = 21
DAILY_SUMMON_LIMIT = 21
# The game shows x/80 on the 压制 icon (Leo 2026-10-09; 70 on 09-28, 60 before).
DAILY_SUPPRESS_LIMIT = 80
DAILY_SUBMAP_LIMIT = DAILY_ABSORB_LIMIT
# These are the usual limits only: each player's HUD shows its own ("3/19"
# for a 召集 not levelled up, 80 for 压制 on Leo's account, 2026-10-09), and
# game updates raise them, so a limit read from the HUD wins for the day.
MAX_DAILY_SKILL_LIMIT = 999


def plausible_limit(value: int) -> bool:
    """A daily skill limit read from the HUD that can be believed."""
    return 1 <= int(value) <= MAX_DAILY_SKILL_LIMIT
# Story cartridge 1 血骑士: its merchant 无聊收集狂大叔 runs the trade.
MERCHANT_CARD_ID = "Q_sp1"
PINNED_CARD_IDS = frozenset({"Q_sp6", "Q_sp18", "Q_sp20"})


class ScreenState(str, Enum):
    HOME = "home"
    CARD_MENU = "card_menu"
    SANDBOX = "sandbox"
    AREA_MAP = "area_map"
    SANDBOX_MAP = "sandbox_map"
    MERCHANT_DIALOG = "merchant_dialog"
    SHOP = "shop"
    COOKING = "cooking"
    LOADING = "loading"
    UNKNOWN = "unknown"


class MapPageMode(str, Enum):
    """Strict visual identity of the three map pages used by story navigation."""

    UNKNOWN = "unknown"
    DIRECT_TELEPORT = "direct_teleport"
    GENERATE_TELEPORT = "generate_teleport"
    SANDBOX_LARGE_MAP = "sandbox_large_map"

    @property
    def is_teleport_map(self) -> bool:
        return self in {
            MapPageMode.DIRECT_TELEPORT,
            MapPageMode.GENERATE_TELEPORT,
        }


class CollectionMapRole(str, Enum):
    MAIN_AREA = "main_area"
    BATTLE_AREA_1 = "battle_area_1"
    BATTLE_AREA_2 = "battle_area_2"

    @property
    def label(self) -> str:
        return {
            CollectionMapRole.MAIN_AREA: "主城区",
            CollectionMapRole.BATTLE_AREA_1: "战斗区域1",
            CollectionMapRole.BATTLE_AREA_2: "战斗区域2",
        }[self]


class CollectionActionState(str, Enum):
    """Durable lifecycle for one daily/card/map-role action.

    ``pending`` means the map-local action is proven but its absolute daily
    counter has not yet been reconciled.  These values are persisted as plain
    strings so old progress files remain easy to inspect and repair.
    """

    PREEXISTING_USED = "preexisting_used"
    ARMED = "armed"
    CLICKED = "clicked"
    LOCAL_DONE = "local_done"
    PENDING = "pending"
    SETTLED = "settled"
    BLOCKED = "blocked"
    VOID = "void"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class CollectionMapTarget:
    role: CollectionMapRole
    title: str
    aliases: tuple[str, ...] = ()
    # Other maps whose names contain this one (角色游戏卡5: 童话镇 inside
    # 童话镇旅馆): a text naming one of them is not this map.
    excludes: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return self.role.value

    @property
    def titles(self) -> tuple[str, ...]:
        return (self.title, *self.aliases)


@dataclass(frozen=True)
class CardSpec:
    card_id: str
    number: int
    name: str
    template: str
    shop_label: str
    collectable: bool = True
    targets: tuple[CollectionMapTarget, ...] = ()
    # The quick bar tab it sits in: "story" (剧情游戏卡), "character" (角色游戏卡)
    # or "event" (活动游戏卡).
    category: str = "story"

    @property
    def label(self) -> str:
        """How messages name the card: 第14章 / 角色卡1 / 活动卡2."""
        if self.category == "character":
            return f"角色卡{self.number}"
        if self.category == "event":
            return f"活动卡{self.number}"
        return f"第{self.number}章"

    @property
    def filter_key(self) -> int | str:
        """Its token in 跑图章节 / 测试章节: 14 for a chapter, "R1" for a
        character card, "E2" for an event card."""
        if self.category == "character":
            return f"R{self.number}"
        if self.category == "event":
            return f"E{self.number}"
        return self.number


@dataclass(frozen=True)
class CalendarEntry:
    item: str
    shop: str
    aliases: tuple[str, ...] = ()
    sell: bool = True
    reserve: int = 0


@dataclass(frozen=True)
class NavigationResult:
    success: bool
    state: ScreenState
    message: str = ""
    map_page_mode: MapPageMode = MapPageMode.UNKNOWN


@dataclass(frozen=True)
class CollectionResult:
    success: bool
    depleted: bool = False
    completed_submaps: int = 0
    message: str = ""


STORY_CARD_NAMES = (
    "血骑士",
    "苍蓝魔女",
    "迷雾神射手",
    "眼镜与猫",
    "沙漠之花",
    "异教塔",
    "愤怒天使",
    "血之狂想曲",
    "铁假面",
    "霍尔蒙克斯",
    "虚假游戏",
    "黑羽毛",
    "雪之歌",
    "神圣审判",
    "复仇的誓言",
    "三国同盟",
    "试炼之路",
    "救赎",
    "被遗忘的战争",
    "剧情游戏卡20",
)

STORY_COLLECTION_MAPS = {
    1: ("卢戈镇", "卢戈森林", "卢戈森林深处"),
    2: ("达雷普镇", "封锁矿山", "禁地矿山"),
    3: ("布伦城", "布伦下水道", "布伦下水道深处"),
    4: ("凯洛镇", "凯洛山", "凯洛山中心处"),
    5: ("亚拉里克城", "亚拉里克遗迹", "亚拉里克遗迹深处"),
    # User demo 2026-09-28: collection on 第1层 / 第6层 / 第5层; 第5层 ("战斗Ⅲ")
    # has no teleport page and is walked to from 第6层 (WALK_ONLY_TARGETS).
    6: ("施塔因之塔第1层", "施塔因之塔第6层", "施塔因之塔第5层"),
    7: ("拉勒凯镇", "洞穴神殿", "隐藏神殿"),
    8: ("罗戴夫镇", "贫民区", "盗贼据点"),
    9: ("雷瓦汀基地", "加尔顿山前段", "加尔顿山后段"),
    10: ("埃兰城", "官邸地下", "官邸大殿"),
    11: ("罗坦王城", "罗坦城门", "城下小镇"),
    12: ("埃克夏城", "埃克夏森林", "埃克夏森林深处"),
    13: ("华特波尔镇", "华特波尔雪山", "记忆裂缝"),
    # Leo 2026-09-30: 居住区域 -> 战斗Ⅱ 左侧回廊 (teleport) -> 战斗Ⅰ 中央回廊 (walk:
    # no activated circle there), like chapter 6; back the same way, walking
    # to 左侧回廊's circle for the town.  Roles follow that order.
    14: ("阿尔卡迪亚居住区域", "剑之神殿左侧回廊", "剑之神殿中央回廊"),
    15: ("科库托斯研究设施", "血刻印量产设施", "重要保管区域"),
    16: ("迪尔索特港口城市", "迪尔索特黑市", "黑市深处"),
    17: ("古代遗迹前哨基地", "试炼之路", "封印祭坛"),
    # Leo 2026-10-10: the safe area too, from 艾琳 ("艾琳到安全區 走到戰鬥一
    # 傳送到戰鬥二"), with the two battle maps that hold resources (09-30:
    # 战斗Ⅰ and 战斗Ⅲ).  暗黑神殿 has no teleport circle: its 圣域 exit is
    # walked (WALK_LABEL_EDGES); back from 圣域 by 艾琳 (TOWN_NAV_ENTRIES).
    # The teleport map has 10 pages (live 2K): 安全 科库托斯暗黑神殿, 安全
    # 记忆岔路口, 战斗Ⅰ 科库托斯圣域, 安全 儿童房, 战斗Ⅱ 阿札尔之屋, then
    # 战斗Ⅲ-Ⅶ 第一/第四/第五/第二/第三记忆空间.
    18: ("科库托斯暗黑神殿", "科库托斯圣域", "第一记忆空间"),
    19: ("亡者安息处", "亡灵游地", "通往神殿之路"),
}
# Chapters whose collection maps are not town + battle I + battle II; the
# first target is where a route restarts.
STORY_COLLECTION_ROLES: dict[int, tuple[CollectionMapRole, ...]] = {}
# Cards counted done once their 压制 badge completes.  Chapter 18 after 战斗Ⅰ
# and 战斗Ⅲ (live 2026-09-30): 压制 complete, 吸取 29 -> 7 left on maps Leo
# does not collect.  Chapter 6 (Leo 2026-10-05): 吸取 keeps 2 after all three
# maps, as some chapters do.
SUPPRESS_ONLY_VERIFIED_CARD_IDS = frozenset({"Q_sp6", "Q_sp18"})
# Cards counted done once their 吸取 badge completes: Nightmare Winter shows
# no 压制 badge at all, before or after the run (live 4K 2026-10-09: only ✦,
# ticked after its three maps; Leo 2026-10-11: nothing left under it = done).
ABSORB_ONLY_VERIFIED_CARD_IDS = frozenset({"Q_ep2"})


# (card, from map, to map) walked through the area map instead of teleporting:
# spots to click on the "from" map's area map (1080 reference), tried in
# order until the map changes.  The area map draws the whole floor in a fixed
# place; which spot reacts depends on where the character stands (live
# 2026-09-28: on the exit itself the ✕ does nothing, but the label or the
# ring just below it works; the character icon can cover the label).
WALK_EDGES = {
    ("Q_sp6", "battle_area_1", "battle_area_2"): ((610, 434), (607, 455), (645, 418)),
    ("Q_sp6", "battle_area_2", "battle_area_1"): ((562, 468), (562, 486), (562, 504)),
}
# Walked by clicking the destination's exit label on the area map (read by
# OCR, then the exit icon under it).  Chapter 14 (live 2K 2026-09-30): 战斗Ⅰ
# 剑之神殿中央回廊 has no activated teleport circle ("没有已激活的魔法阵"); the
# town and 战斗Ⅱ 左侧回廊 have one.  The labels read at 1.00 confidence.  The
# value is the label's centre on the area map (1080p; the map draws each floor
# in a fixed place, every read so far within 2 px), used when the label cannot
# be read: the character's own icon covers it at that exit (live 2K after an
# expulsion put the character there).
WALK_LABEL_EDGES = {
    ("Q_sp14", "battle_area_1", "battle_area_2"): (609, 719),
    ("Q_sp14", "battle_area_2", "battle_area_1"): (484, 460),
    # Character card 3 (live 4K 2026-10-03): 战斗Ⅱ 禁闭室 has no circle; the
    # walk from 战斗Ⅰ took 4 s.  战斗Ⅰ has a patrolling 墨镜大叔 (Leo: seen
    # from the front -> expelled, the walk then goes on by itself).
    ("Q_cp3", "battle_area_1", "battle_area_2"): (631, 333),
    ("Q_cp3", "battle_area_2", "battle_area_1"): (739, 563),
    # Chapter 18 (live 4K 2026-10-10, 1080p): 暗黑神殿 has no circle; the
    # 科库托斯圣域 label's exit took 4.6 s, no patrol.  Clicked at (525, 296),
    # the label centre + 18 px.
    ("Q_sp18", "main_area", "battle_area_1"): (525, 278),
}
# Areas without a teleport circle, left through an area-map exit for a
# neighbour that has one: card -> (that area, the neighbour).  Chapter 18
# (live 4K 2026-10-10): the quick switch and 艾琳 both put the character in
# 安全 科库托斯暗黑神殿, which has no circle and no 狩猎场 in its ≡ menu; its
# 科库托斯圣域 exit is a free 4.6 s walk, and 圣域's circle is found (0.949).
# Without a portal skill on the bar this is the only way out.
CIRCLE_EXIT_WALKS = {
    "Q_sp18": ("科库托斯暗黑神殿", "科库托斯圣域"),
}
# ≡-menu entry for the reverse route's last step into the town (restarts use
# 狩猎场, else 艾琳, for every card: navigator_constants).  Chapter 14 (11 s):
# 左侧回廊's menu lists 艾琳.  Walking to its circle from the 中央回廊 side got
# the character expelled by the 光明监视者 in the route test, which presses no
# skills; Leo: "先壓制就不會碰到怪了", then "傳送艾琳比較穩 那就先傳艾琳".
# Character card 3: 禁闭室's menu lists 艾琳 and no 狩猎场 (live 4K
# 2026-10-03); 艾琳 also keeps the way back clear of 战斗Ⅰ's patrol.
TOWN_NAV_ENTRIES = {
    "Q_sp14": "艾琳",
    "Q_cp3": "艾琳",
    # Chapter 18: 圣域 -> 艾琳 in 暗黑神殿 (free, live 4K 2026-10-10; Leo:
    # "戰鬥二開始就 傳送到戰鬥一 然後 傳回艾琳").
    "Q_sp18": "艾琳",
    # Event cards without a teleport circle (Leo 2026-10-09).
    **{card_id: "艾琳" for card_id in ("Q_ep1", "Q_ep3", "Q_ep5", "Q_ep7")},
}
# Restarts (a start on any map but the first or last, or a failed move) go to
# the town through this ≡-menu entry first, even when standing on a circle.
# Character card 3 (Leo 2026-10-03: "如果一開始 玩家在戰鬥一 或者 三 就先傳回艾琳
# 然後再走去魔法陣繼續").
RESTART_NAV_ENTRIES = {
    "Q_cp3": "艾琳",
    # Chapter 18 (Leo 2026-10-10: "在其他地方就 先傳回艾琳").
    "Q_sp18": "艾琳",
    # Event cards: too close to an exit to click it -> 艾琳, then the exit
    # (Leo 2026-10-09: "人物和傳送點貼太近有時候不好點 那就直接傳送回艾琳").
    **{card_id: "艾琳" for card_id in ("Q_ep1", "Q_ep3", "Q_ep5", "Q_ep7")},
}
# Cards whose patrol catch is left alone: the game reloads the map and walks
# on by itself, so the exit walk keeps waiting instead of clicking again
# (Leo 2026-10-03, card 3's 墨镜大叔: "最好方法就是不處理 放著總會過的").
RESUMING_WALK_CARD_IDS = frozenset(
    # Event-card walks are long (Memory Edge 40 s with a field battle on
    # the way, live 4K 2026-10-09): wait for the walk to end.
    {"Q_cp3", "Q_ep1", "Q_ep3", "Q_ep5", "Q_ep7"}
)
# Cards whose last map is left for the town (≡ menu, TOWN_NAV_ENTRIES)
# instead of walking back: a start there runs last -> town -> the rest
# forward.  Card 3 (live 4K 2026-10-04): arriving at 禁闭室 by the walk
# leaves the character on its exit, where clicking the 拍卖场 exit does
# nothing (~9 s lost before the restart); Leo left the call to Claude.
LAST_MAP_THEN_TOWN_CARD_IDS = frozenset({"Q_cp3"})
# How long such a walk may keep going, catches included (Leo: 60 s).
RESUMING_WALK_TIMEOUT = 60.0


def _story_collection_targets(number: int) -> tuple[CollectionMapTarget, ...]:
    titles = STORY_COLLECTION_MAPS.get(number)
    if titles is None:
        return ()
    roles = STORY_COLLECTION_ROLES.get(number, tuple(CollectionMapRole))
    return tuple(
        CollectionMapTarget(role, title)
        for role, title in zip(roles, titles, strict=True)
    )


STORY_CARDS = tuple(
    CardSpec(
        card_id=f"Q_sp{number}",
        number=number,
        name=name,
        template=f"image/Cartridges/Q_sp{number}.png",
        shop_label=f"S{number}:{name}",
        collectable=number in STORY_COLLECTION_MAPS,
        targets=_story_collection_targets(number),
    )
    for number, name in enumerate(STORY_CARD_NAMES, start=1)
)

STORY_COLLECTABLE_CARDS = tuple(card for card in STORY_CARDS if card.collectable)


CHARACTER_CARD_NAMES = (
    "杰登之门",
    "火晶片",
    "美丽无望",
    "大逃脱",
    "鲁的迷宫",
    "御剑传",
    "合约之战",
)
_MAIN = CollectionMapRole.MAIN_AREA
_BATTLE_1 = CollectionMapRole.BATTLE_AREA_1
_BATTLE_2 = CollectionMapRole.BATTLE_AREA_2
# 角色游戏卡 (Leo 2026-09-30; card 3 added 2026-10-03).
# The tab lists 10 cards; 1-7 carry 吸取/压制 badges (8 and 10 none, 9 chests).
# Area-map pages read live 2K 2026-09-30:
#   1 学校1楼 / 学校2楼 / 学校3楼 (安全), 战斗Ⅰ 学校地下, 学校操场 (安全)
#   3 上流社会派对会场 (安全), 战斗Ⅰ 地下秘密拍卖场, 战斗Ⅱ 禁闭室, 战斗Ⅲ 拍卖仓库
#     (Ⅱ and Ⅲ have no circle; read live 4K 2026-10-03)
#   2 避难所166 (安全), 战斗Ⅰ 废墟地道（前段）, 战斗Ⅱ 废墟地道（后段）
#   4 商场4楼 (安全), 战斗Ⅰ 商场3楼, 战斗Ⅱ 商场2楼, 战斗Ⅲ 商场1楼
#   5 童话镇 (安全), 战斗Ⅰ 魔女居林, 童话镇旅馆 (安全)
#   6 西风镇 (安全), 战斗Ⅰ 西风竹林, 战斗Ⅱ 妖怪森林, 战斗Ⅲ 妖怪镇
#   7 凯那尔工业1楼 / 凯那尔工业2楼 (安全), 战斗Ⅰ 卡勒塔市
# As for the story cards: the first safe map (吸收) and the first two battle
# maps (吸收/召集/压制); cards with one battle map have two targets.  The
# parentheses of 废墟地道（前段） read as 道/直 in the field's OCR, hence the
# short aliases.
CHARACTER_COLLECTION_TARGETS = {
    1: (
        CollectionMapTarget(_MAIN, "学校1楼"),
        CollectionMapTarget(_BATTLE_1, "学校地下"),
    ),
    2: (
        CollectionMapTarget(_MAIN, "避难所166", aliases=("避难所",)),
        CollectionMapTarget(_BATTLE_1, "废墟地道（前段）", aliases=("前段",)),
        CollectionMapTarget(_BATTLE_2, "废墟地道（后段）", aliases=("后段",)),
    ),
    # Leo 2026-10-03: 安全 + 战斗Ⅰ + 战斗Ⅱ; 战斗Ⅱ 禁闭室 has no teleport
    # circle and is walked to from 战斗Ⅰ (WALK_LABEL_EDGES), like ch14.
    3: (
        CollectionMapTarget(_MAIN, "上流社会派对会场"),
        CollectionMapTarget(_BATTLE_1, "地下秘密拍卖场"),
        CollectionMapTarget(_BATTLE_2, "禁闭室"),
    ),
    4: (
        CollectionMapTarget(_MAIN, "商场4楼"),
        CollectionMapTarget(_BATTLE_1, "商场3楼"),
        CollectionMapTarget(_BATTLE_2, "商场2楼"),
    ),
    5: (
        CollectionMapTarget(_MAIN, "童话镇", excludes=("童话镇旅馆",)),
        CollectionMapTarget(_BATTLE_1, "魔女居林"),
    ),
    6: (
        CollectionMapTarget(_MAIN, "西风镇"),
        CollectionMapTarget(_BATTLE_1, "西风竹林"),
        CollectionMapTarget(_BATTLE_2, "妖怪森林"),
    ),
    7: (
        CollectionMapTarget(_MAIN, "凯那尔工业1楼"),
        CollectionMapTarget(_BATTLE_1, "卡勒塔市"),
    ),
}
CHARACTER_CARDS = tuple(
    CardSpec(
        card_id=f"Q_cp{number}",
        number=number,
        name=name,
        template=f"image/Cartridges/Q_cp{number}.png",
        shop_label=f"R{number}:{name}",
        collectable=number in CHARACTER_COLLECTION_TARGETS,
        targets=CHARACTER_COLLECTION_TARGETS.get(number, ()),
        category="character",
    )
    for number, name in enumerate(CHARACTER_CARD_NAMES, start=1)
)

# 活动游戏卡: the permanent event cards (Leo 2026-10-09), numbered as the
# shop numbers them (E1/E2/E3/E5/E7; 4 and 6 are time-limited).  Walked live
# at 4K 2026-10-09 (docs/dev-notes/event-cartridges-2026-10-09.md):
#   1 Summer Knight: 泳池派对场 (安全), 战斗Ⅰ 派对会场角落
#   2 Nightmare Winter: 战斗Ⅰ 恶梦之城1, 战斗Ⅱ 恶梦之城2, 雷瓦汀据点 (安全,
#     a shop, the LAST teleport page); every map has a teleport circle
#   3 Beachside Angels: 海岸沙滩 (安全), 战斗Ⅰ 海岸椰林
#   5 Memory Edge: 底层居住区 (安全), 战斗Ⅰ 第4区, 安全 ??? (unopened)
#   7 Splash Queen: 水上乐园室内泳池 (安全), 战斗Ⅰ 泼水音乐节活动现场,
#     水上乐园物资仓库 (安全)
# Cards 1/3/5/7 have no teleport circle: the two maps are walked between on
# the area map (EVENT_WALK_EDGES).
EVENT_CARD_NAMES = {
    1: "夏日骑士",
    2: "恶梦之冬",
    3: "海滨天使",
    5: "记忆边缘",
    7: "戏水女王",
}
EVENT_COLLECTION_TARGETS = {
    1: (
        CollectionMapTarget(_MAIN, "泳池派对场"),
        CollectionMapTarget(_BATTLE_1, "派对会场角落"),
    ),
    2: (
        CollectionMapTarget(_MAIN, "雷瓦汀据点"),
        CollectionMapTarget(_BATTLE_1, "恶梦之城1", excludes=("恶梦之城2",)),
        CollectionMapTarget(_BATTLE_2, "恶梦之城2", excludes=("恶梦之城1",)),
    ),
    3: (
        CollectionMapTarget(_MAIN, "海岸沙滩"),
        CollectionMapTarget(_BATTLE_1, "海岸椰林"),
    ),
    5: (
        CollectionMapTarget(_MAIN, "底层居住区"),
        CollectionMapTarget(_BATTLE_1, "第4区"),
    ),
    7: (
        CollectionMapTarget(_MAIN, "水上乐园室内泳池", aliases=("室内泳池",)),
        CollectionMapTarget(_BATTLE_1, "泼水音乐节活动现场", aliases=("音乐节活动现场",)),
    ),
}
EVENT_CARDS = tuple(
    CardSpec(
        card_id=f"Q_ep{number}",
        number=number,
        name=name,
        template=f"image/Cartridges/Q_ep{number}.png",
        shop_label=f"E{number}:{name}",
        targets=EVENT_COLLECTION_TARGETS[number],
        category="event",
    )
    for number, name in EVENT_CARD_NAMES.items()
)
WALKED_EVENT_CARD_IDS = frozenset({"Q_ep1", "Q_ep3", "Q_ep5", "Q_ep7"})
# (card, from, to) -> area-map spots (1080 ref) tried in order until the map
# closes, as WALK_EDGES; a spot may open the small list of what stands
# there (战斗区 / 旅馆 / 艾琳...), whose 战斗区 / 安全区 row then starts the
# walk (navigator_sandbox._click_exit_picker).  Standing on the exit itself
# the spot often does nothing (Leo: 太近不好點): the failed move restarts
# from 艾琳 (RESTART_NAV_ENTRIES), from where the spot works (live 4K
# 2026-10-09, cards 1 and 3).
EVENT_WALK_EDGES = {
    # Summer Knight: one ring each way; on the battle page just below the
    # ring worked when standing on it.
    ("Q_ep1", "main_area", "battle_area_1"): ((682, 392),),
    ("Q_ep1", "battle_area_1", "main_area"): ((492, 768), (492, 745)),
    # Beachside Angels: two battle exits share one picker; two house rings
    # on the battle page.
    ("Q_ep3", "main_area", "battle_area_1"): ((733, 689), (690, 727)),
    ("Q_ep3", "battle_area_1", "main_area"): ((326, 411), (371, 365)),
    # Memory Edge: the 第4区 label; the battle map's bottom exit (where the
    # walk from the town arrives), else its far exit (a 40 s walk).
    ("Q_ep5", "main_area", "battle_area_1"): ((480, 253), (480, 272), (736, 449)),
    ("Q_ep5", "battle_area_1", "main_area"): ((537, 718), (537, 735), (392, 548), (392, 567)),
    # Splash Queen: the 水上乐园室内泳池 label / its ring, and the pool's
    # battle ring.
    ("Q_ep7", "battle_area_1", "main_area"): ((396, 384), (395, 402)),
    ("Q_ep7", "main_area", "battle_area_1"): ((748, 585), (748, 565)),
}

# The weekly map run: story chapters, then character cards, then event cards.
COLLECTABLE_CARDS = (
    STORY_COLLECTABLE_CARDS
    + tuple(card for card in CHARACTER_CARDS if card.collectable)
    + EVENT_CARDS
)
CARD_BY_ID = {card.card_id: card for card in (*STORY_CARDS, *CHARACTER_CARDS, *EVENT_CARDS)}


CHARACTER_SHOPS = {
    "R1": "R1:杰登之门",
    "R2": "R2:火晶片",
    "R3": "R3:美丽无望",
    "R4": "R4:大逃脱",
    "R5": "R5:鲁的迷宫",
    "R6": "R6:御剑传",
    "R7": "R7:合约之战",
}
# 活动卡带编号并不连续，须与 data.py 的选择模板映射一致。
EVENT_SHOPS = {
    "E1": "E1:夏日骑士",
    "E2": "E2:恶梦之冬",
    "E3": "E3:海滨天使",
    "E5": "E5:记忆边缘",
    "E7": "E7:戏水女王",
}

KNOWN_SHOPS = {
    **{f"S{card.number}": card.shop_label for card in STORY_CARDS},
    **CHARACTER_SHOPS,
    **EVENT_SHOPS,
}


DEFAULT_RECIPES = (
    "卢戈山参烤串",
    "煤炭饼干",
    "闪闪铁板虾",
    "透明沙拉",
    "地狱火紫菜包饭",
)

# 香草牛排 and 冰镇甜点 first (user's trade sheet, 2026-09-29: they share
# ingredients with other dishes); then red, yellow, blue as upstream ordered.
DEFAULT_COOKING_RECIPES = (
    "香草牛排",
    "冰镇甜点",
    "巧克力鸡尾酒",
    "蜂蜜黄油杏仁",
    "鱼子酱蛋包饭",
    "火烤鱼板棒",
    "泰瑞丝派",
    "橄榄油意面",
    "三明治便当",
)

OPTIONAL_COOKING_RECIPES = DEFAULT_RECIPES
FINAL_COOKING_RECIPE = "街头烤鸡肉串"

COOKING_RECIPE_TEMPLATES = {
    "巧克力鸡尾酒": "image/Shop/cook_Chocolate Cocktail.png",
    "蜂蜜黄油杏仁": "image/Shop/cook_Honey Butter Almonds.png",
    "鱼子酱蛋包饭": "image/Shop/cook_Caviar Omurice.png",
    "香草牛排": "image/Shop/cook_Vanilla Steak.png",
    "冰镇甜点": "image/Shop/cook_Iced Dessert.png",
    "泰瑞丝派": "image/Shop/cook_Teresse Pie.png",
    "橄榄油意面": "image/Shop/cook_Olive Oil Pasta.png",
    "三明治便当": "image/Shop/cook_Sandwich Lunch Box.png",
    "火烤鱼板棒": "image/Shop/cook_Grilled Fish Cake Skewer.png",
    FINAL_COOKING_RECIPE: "image/Shop/cook_Street Grilled Chicken Skewer.png",
}

RECIPE_TEMPLATES = {
    "卢戈山参烤串": "image/Shop/cook_Lugas Ginseng Skewer.png",
    "煤炭饼干": "image/Shop/cook_Coal Cookies.png",
    "闪闪铁板虾": "image/Shop/cook_Sparkling Griddle Shrimp.png",
    "透明沙拉": "image/Shop/cook_Transparent Salad.png",
    "地狱火紫菜包饭": "image/Shop/cook_Hellfire Gimbap.png",
}
COOKING_RECIPE_TEMPLATES.update(RECIPE_TEMPLATES)

DEFAULT_SALE_WHITELIST = (
    "蜂蜜黄油杏仁",
    "香草牛排",
    "冰镇甜点",
    "三角美乃滋饭团",
    "鱼子酱蛋包饭",
    "炸三文鱼便当",
    "巧克力鸡尾酒",
    "火烤鱼板棒",
    "卢戈山参烤串",
    "煤炭饼干",
    "闪闪铁板虾",
    "透明沙拉",
    "地狱火紫菜包饭",
    "米",
    "土豆",
    "泰瑞丝派",
    "黄油",
    "甜辣酱",
    "藏红花",
    "萝卜缨",
    "哈密瓜",
)
