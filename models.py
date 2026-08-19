# models.py
from enum import Enum
import random
from datetime import datetime
import uuid

FOUR_CONSORTS = ["淑妃", "德妃", "贤妃", "宸妃"]
TITLED_CONSORT_POWER = 12  # 带封号的妃（位份仍为妃）

RANK_POWER = {
    "宫女": 0, "更衣": 1, "官女子": 2, "秀女": 3, "答应": 4, "常在": 5,
    "贵人": 6, "才人": 7, "美人": 8, "婕妤": 9, "嫔": 10, "妃": 11,
    "淑妃": 13, "德妃": 14, "贤妃": 15, "宸妃": 16,
    "贵妃": 17, "皇贵妃": 18, "皇后": 19,
}

def normalize_rank_name(rank_name):
    if rank_name in RANK_POWER or rank_name == "妃":
        return rank_name
    return rank_name

def get_rank_power(rank_name, nobletitle=None):
    """位份实力：妃 < 带封号的妃 < 四妃。"""
    rank_name = normalize_rank_name(rank_name)
    if rank_name == "妃" and nobletitle:
        return TITLED_CONSORT_POWER
    return RANK_POWER.get(rank_name, 0)

def is_titled_consort(rank_name, nobletitle=None):
    return rank_name == "妃" and nobletitle

class Rank(Enum):
    宫女 = 0
    更衣 = 1
    官女子 = 2
    秀女 = 3
    答应 = 4
    常在 = 5
    贵人 = 6
    才人 = 7
    美人 = 8
    婕妤 = 9
    嫔 = 10
    妃 = 11
    淑妃 = 12
    德妃 = 13
    贤妃 = 14
    宸妃 = 15
    贵妃 = 16
    皇贵妃 = 17
    皇后 = 18

class EmperorPersonality(Enum):
    明君 = "明君"
    昏君 = "昏君"
    痴情 = "痴情"
    多疑 = "多疑"

class Storyline(Enum):
    主线 = "主线"
    爱情线 = "爱情线"
    权谋线 = "权谋线"
    自由线 = "自由线"

NOBLETITLES = [
    "贤", "淑", "德", "容", "华", "仪", "婉", "柔", "娴", "静",
    "惠", "康", "庄", "和", "顺", "慈", "宁", "昭", "敬", "端",
    "良", "懿", "敏", "慧", "安", "宁", "禧", "纯", "瑾", "瑜"
]

class Servant:
    def __init__(self, name, type_, loyalty=50, skill=30):
        self.name = name
        self.type = type_
        self.loyalty = loyalty
        self.skill = skill
        self.is_active = True
        self.hire_day = 0
    def to_dict(self):
        return {"name": self.name, "type": self.type, "loyalty": self.loyalty, "skill": self.skill, "is_active": self.is_active, "hire_day": self.hire_day}
    @classmethod
    def from_dict(cls, data):
        s = cls(data["name"], data["type"], data["loyalty"], data["skill"])
        s.is_active = data.get("is_active", True)
        s.hire_day = data.get("hire_day", 0)
        return s

class GameState:
    # 属性上限配置
    ATTR_MAX = {
        "容貌": 100,
        "才情": 100,
        "心计": 100,
        "宠爱": 999,
        "威望": 3000,
        "健康": 100,
        "才艺": 100,
        "谋略": 100,
        "魅力": 100,
        "福运": 100,
        "倾向": 100
    }

    def __init__(self, player_id, start_rank=Rank.秀女):
        self.player_id = player_id
        self.rank = start_rank
        self.nobletitle = None
        self.name = "未命名"
        self.family_background = "未知"
        self.family_meta = {}
        self.appearance = ""
        self.talent = ""
        self.personality = ""
        self.background_desc = ""
        self.traits = []
        self.custom_story = ""
        self.age = 16
        self.current_time = "辰时"
        # 日历
        self.day = 1
        self.month = 1
        self.year = 1
        # 行动点
        self.max_actions = 7
        self.remaining_actions = 7

        # 属性初始化
        self.attributes = {
            "容貌": 60,
            "才情": 50,
            "心计": 40,
            "宠爱": 30,
            "威望": 20,
            "健康": 80,
            "才艺": 40,
            "谋略": 35,
            "魅力": 45,
            "福运": 30,
            "倾向": 35
        }
        self.silver = 100
        self.servants = []
        self.max_servants = 6 + self.rank.value // 2
        self.relationships = {}
        self.story_flags = []
        self.main_story_progress = 0
        self.storyline = Storyline.主线
        self.ending_unlocked = None
        self.inventory = []
        self.important_memories = []
        self.history = []
        self.attr_change_log = []
        self.romance_mode = False
        self.custom_prompt = ""
        self.is_pregnant = False
        self.pregnancy_month = 0
        self.monthly_intimacy = 0
        self.children = []
        self.has_children = False
        self.rivalries = {}
        self.alliances = {}
        self.emperor = {
            "name": "萧景琰",
            "personality": random.choice([p.value for p in EmperorPersonality]),
            "age": random.randint(25, 55),
            "stats": {"威严": random.randint(40, 90), "仁德": random.randint(30, 85), "勤政": random.randint(30, 85), "好色": random.randint(10, 80)},
            "favor_factors": {"明君": {"容貌": 0.2, "才情": 0.5, "心计": 0.3}, "昏君": {"容貌": 0.8, "才情": 0.1, "心计": 0.1}, "痴情": {"容貌": 0.3, "才情": 0.3, "心计": 0.4}, "多疑": {"容貌": 0.2, "才情": 0.2, "心计": 0.6}}
        }
        self.npcs = {}
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        # 晋升事件标记
        self._pending_promotion = None
        self._promotion_fail_count = 0
        self._promotion_done = False  # 本旬晋升标志
        self.scandal_strikes = 0  # 宫斗丑闻累积，满则更易降位
        self.rank_periods = 0  # 现任位份已历旬数（资历）
        self.last_duel_period = None
        self._active_duel = None
        self.client_id = None

    def get_attr_max(self, attr_name):
        return self.ATTR_MAX.get(attr_name, 100)

    def get_attr_percentage(self, attr_name):
        val = self.attributes.get(attr_name, 0)
        max_val = self.get_attr_max(attr_name)
        return min(100, int((val / max_val) * 100)) if max_val > 0 else 0

    # 日历方法：每次推进 10 天（一旬）
    def advance_calendar(self):
        self.day += 10
        while self.day > 30:
            self.day -= 30
            self.month += 1
            if self.month > 12:
                self.month = 1
                self.year += 1

    def get_calendar_str(self):
        if self.day <= 10:
            period = "上旬"
        elif self.day <= 20:
            period = "中旬"
        else:
            period = "下旬"
        return f"建元{self.year}年{self.month}月{period}"

    def get_full_date_str(self):
        return f"建元{self.year}年{self.month}月{self.day}日"

    # 行动点方法
    def reset_actions(self):
        self.remaining_actions = self.max_actions

    def can_act(self):
        return self.remaining_actions > 0

    def consume_action(self):
        if self.remaining_actions <= 0:
            return False
        self.remaining_actions -= 1
        return True

    # 其他方法
    def get_emperor_factor(self):
        personality = self.emperor["personality"]
        return self.emperor["favor_factors"].get(personality, self.emperor["favor_factors"]["明君"])

    def get_display_rank(self):
        if self.nobletitle:
            return f"{self.nobletitle}{self.rank.name}"
        return self.rank.name

    def grant_nobletitle(self):
        favor = self.attributes.get("宠爱", 0)
        prestige = self.attributes.get("威望", 0)
        rank_order = [
            "宫女", "更衣", "官女子", "秀女", "答应", "常在", "贵人", "才人", "美人", "婕妤",
            "嫔", "妃", "淑妃", "德妃", "贤妃", "宸妃", "贵妃", "皇贵妃", "皇后",
        ]
        current_idx = rank_order.index(self.rank.name) if self.rank.name in rank_order else 0
        if current_idx >= rank_order.index("贵人") and favor >= 65 and prestige >= 55:
            if self.rank.name != "妃":
                return None
            if self.nobletitle:
                if random.random() < 0.2:
                    new_title = random.choice(NOBLETITLES)
                    while new_title == self.nobletitle:
                        new_title = random.choice(NOBLETITLES)
                    old_title = self.nobletitle
                    self.nobletitle = new_title
                    return f"封号更换：『{old_title}』→『{new_title}』"
                return None
            else:
                self.nobletitle = random.choice(NOBLETITLES)
                return f"皇帝赐封号：『{self.nobletitle}』"
        return None

    def add_servant(self, servant):
        if len(self.servants) >= self.max_servants:
            return False, "已有太多宫女太监，需先遣散一些。"
        servant.hire_day = self.day
        self.servants.append(servant)
        return True, f"招募了{servant.name}（{servant.type}）"

    def remove_servant(self, name):
        for i, s in enumerate(self.servants):
            if s.name == name and s.is_active:
                s.is_active = False
                self.servants.pop(i)
                return True, f"遣散了{name}"
        return False, "未找到该宫女/太监"

    def get_active_servants(self):
        return [s for s in self.servants if s.is_active]

    def add_attr_change(self, changes, reason=""):
        self.attr_change_log.append({"day": self.day, "time": self.current_time, "changes": changes.copy(), "reason": reason})
        if len(self.attr_change_log) > 50:
            self.attr_change_log.pop(0)

    def add_memory(self, event):
        self.important_memories.append(f"[第{self.day}天] {event}")
        if len(self.important_memories) > 20:
            self.important_memories.pop(0)

    def get_recent_memories(self, count=3):
        return self.important_memories[-count:] if self.important_memories else []

    def to_dict(self):
        return {
            "player_id": self.player_id,
            "rank": self.rank.name,
            "nobletitle": self.nobletitle,
            "display_rank": self.get_display_rank(),
            "name": self.name,
            "family_background": self.family_background,
            "family_meta": getattr(self, "family_meta", {}),
            "appearance": getattr(self, "appearance", ""),
            "talent": getattr(self, "talent", ""),
            "personality": getattr(self, "personality", ""),
            "background_desc": getattr(self, "background_desc", ""),
            "traits": getattr(self, "traits", []),
            "custom_story": getattr(self, "custom_story", ""),
            "age": self.age,
            "current_time": self.current_time,
            "day": self.day,
            "month": self.month,
            "year": self.year,
            "calendar_str": self.get_calendar_str(),
            "max_actions": self.max_actions,
            "remaining_actions": self.remaining_actions,
            "attributes": self.attributes,
            "attr_max": self.ATTR_MAX,
            "relationships": self.relationships,
            "story_flags": self.story_flags,
            "main_story_progress": self.main_story_progress,
            "storyline": self.storyline.value,
            "inventory": self.inventory,
            "silver": self.silver,
            "important_memories": self.important_memories,
            "history": self.history[-50:],
            "emperor": self.emperor,
            "npcs": self.npcs,
            "servants": [s.to_dict() for s in self.get_active_servants()],
            "is_pregnant": self.is_pregnant,
            "pregnancy_month": self.pregnancy_month,
            "monthly_intimacy": getattr(self, "monthly_intimacy", 0),
            "children": self.children,
            "has_children": self.has_children,
            "rivalries": self.rivalries,
            "alliances": self.alliances,
            "attr_change_log": self.attr_change_log[-20:],
            "romance_mode": self.romance_mode,
            "custom_prompt": self.custom_prompt,
            "last_duel_period": getattr(self, "last_duel_period", None),
            "scandal_strikes": getattr(self, "scandal_strikes", 0),
            "rank_periods": getattr(self, "rank_periods", 0),
            "client_id": getattr(self, "client_id", None),
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat()
        }

    def to_save_data(self):
        return {"version": "1.5", "save_time": datetime.now().isoformat(), "game_state": self.to_dict()}

    @classmethod
    def from_save_data(cls, save_data):
        try:
            data = save_data.get("game_state", save_data)
            rank_name = normalize_rank_name(data.get("rank", "秀女"))
            try:
                rank = Rank[rank_name]
            except KeyError:
                rank = Rank.秀女
            player_id = data.get("player_id", "unknown")
            game_state = cls(player_id, rank)
            game_state.name = data.get("name", "未命名")
            game_state.family_background = data.get("family_background", "未知")
            game_state.family_meta = data.get("family_meta", {})
            game_state.appearance = data.get("appearance", "")
            game_state.talent = data.get("talent", "")
            game_state.personality = data.get("personality", "")
            game_state.background_desc = data.get("background_desc", "")
            game_state.traits = data.get("traits", [])
            game_state.custom_story = data.get("custom_story", "")
            game_state.age = data.get("age", 16)
            game_state.current_time = data.get("current_time", "辰时")
            game_state.day = data.get("day", 1)
            game_state.month = data.get("month", 1)
            game_state.year = data.get("year", 1)
            game_state.nobletitle = data.get("nobletitle")
            game_state.romance_mode = data.get("romance_mode", False)
            game_state.custom_prompt = data.get("custom_prompt", "")
            saved_attrs = data.get("attributes", {})
            default_attrs = {"容貌": 60, "才情": 50, "心计": 40, "宠爱": 30, "威望": 20, "健康": 80, "才艺": 40, "谋略": 35, "魅力": 45, "福运": 30, "倾向": 35}
            for key, default_val in default_attrs.items():
                game_state.attributes[key] = saved_attrs.get(key, default_val)
            game_state.silver = data.get("silver", 100)
            game_state.relationships = data.get("relationships", {})
            game_state.story_flags = data.get("story_flags", [])
            game_state.main_story_progress = data.get("main_story_progress", 0)
            game_state.inventory = data.get("inventory", [])
            game_state.important_memories = data.get("important_memories", [])
            game_state.history = data.get("history", [])
            game_state.attr_change_log = data.get("attr_change_log", [])
            game_state.emperor = data.get("emperor", {"name": "萧景琰", "personality": "明君", "age": 35, "stats": {"威严": 60, "仁德": 50, "勤政": 50, "好色": 40}, "favor_factors": {"明君": {"容貌": 0.2, "才情": 0.5, "心计": 0.3}, "昏君": {"容貌": 0.8, "才情": 0.1, "心计": 0.1}, "痴情": {"容貌": 0.3, "才情": 0.3, "心计": 0.4}, "多疑": {"容貌": 0.2, "才情": 0.2, "心计": 0.6}}})
            game_state.npcs = data.get("npcs", {})
            for npc in game_state.npcs.values():
                if "rank" in npc:
                    npc["rank"] = normalize_rank_name(npc["rank"])
                # Ensure each child has a stable child_id for migrations and future references
                if "children" in npc and isinstance(npc["children"], list):
                    for child in npc["children"]:
                        if "child_id" not in child:
                            child["child_id"] = uuid.uuid4().hex
            servants_data = data.get("servants", [])
            game_state.servants = []
            for sd in servants_data:
                s = Servant(sd["name"], sd["type"], sd["loyalty"], sd["skill"])
                s.is_active = sd.get("is_active", True)
                s.hire_day = sd.get("hire_day", 0)
                game_state.servants.append(s)
            game_state.max_servants = 6 + game_state.rank.value // 2
            game_state.is_pregnant = data.get("is_pregnant", False)
            game_state.pregnancy_month = data.get("pregnancy_month", 0)
            game_state.monthly_intimacy = data.get("monthly_intimacy", 0)
            game_state.children = data.get("children", [])
            # Ensure migrated top-level children entries have child_id for backward compatibility
            if isinstance(game_state.children, list):
                for child in game_state.children:
                    if isinstance(child, dict) and "child_id" not in child:
                        child["child_id"] = uuid.uuid4().hex
            game_state.has_children = data.get("has_children", False)
            game_state.rivalries = data.get("rivalries", {})
            game_state.alliances = data.get("alliances", {})
            game_state.created_at = data.get("created_at", datetime.now().isoformat())
            game_state.updated_at = datetime.now().isoformat()
            game_state.max_actions = data.get("max_actions", 7)
            game_state.remaining_actions = data.get("remaining_actions", 7)
            game_state.last_duel_period = data.get("last_duel_period")
            game_state._pending_promotion = None
            game_state._promotion_fail_count = data.get("_promotion_fail_count", 0)
            game_state._promotion_done = data.get("_promotion_done", False)
            game_state.scandal_strikes = data.get("scandal_strikes", 0)
            game_state.rank_periods = data.get("rank_periods", 0)
            game_state.client_id = data.get("client_id")
            storyline_value = data.get("storyline", "主线")
            for sl in Storyline:
                if sl.value == storyline_value:
                    game_state.storyline = sl
                    break
            return game_state
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise ValueError(f"恢复存档失败: {str(e)}")