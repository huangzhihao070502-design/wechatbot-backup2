"""
角色卡（Persona）管理系统
为 AI 回复注入人物性格、语言风格、背景设定等角色扮演能力
"""

import json
import uuid
from pathlib import Path
from typing import Optional, Dict, List

PERSONAS_FILE = "personas.json"


class PersonaManager:
    """管理角色卡的加载、保存、查询和 prompt 构建"""

    def __init__(self):
        self.personas: Dict[str, dict] = {}          # persona_id → persona_data
        self.user_persona_map: Dict[str, str] = {}    # user_id → persona_id（逐用户指定）
        self._global_persona_id: Optional[str] = None # 全局角色卡 ID
        self._persona_mode = "none"                   # "none" | "global" | "per_user"
        self._load()

    # ─── 持久化 ─────────────────────────────────

    def _path(self) -> Path:
        return Path(PERSONAS_FILE)

    def _load(self):
        try:
            if self._path().exists():
                with open(self._path(), "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.personas = data.get("personas", {})
                self.user_persona_map = data.get("user_persona_map", {})
                self._global_persona_id = data.get("global_persona_id")
                self._persona_mode = data.get("persona_mode", "none")
                pc = len(self.personas)
                uc = len(self.user_persona_map)
                print(f"[角色卡] 已加载 {pc} 个角色, {uc} 个用户映射, 模式={self._persona_mode}")
        except Exception as e:
            print(f"[角色卡] 加载失败: {e}")

    def _save(self):
        try:
            data = {
                "personas": self.personas,
                "user_persona_map": self.user_persona_map,
                "global_persona_id": self._global_persona_id,
                "persona_mode": self._persona_mode,
            }
            with open(self._path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[角色卡] 保存失败: {e}")

    # ─── CRUD ──────────────────────────────────

    def add_persona(self, data: dict) -> str:
        """新增角色卡，返回 ID"""
        pid = "persona_" + uuid.uuid4().hex[:12]
        now = __import__("time").time()
        self.personas[pid] = {
            "id": pid,
            "name": data.get("name", "未命名角色"),
            "personality": data.get("personality", ""),
            "language_style": data.get("language_style", ""),
            "background": data.get("background", ""),
            "behavior": data.get("behavior", ""),
            "other_details": data.get("other_details", ""),
            "created_at": now,
            "updated_at": now,
        }
        self._save()
        print(f"[角色卡] 新增: {self.personas[pid]['name']} ({pid})")
        return pid

    def update_persona(self, persona_id: str, data: dict) -> bool:
        """更新已有角色卡"""
        if persona_id not in self.personas:
            return False
        card = self.personas[persona_id]
        for key in ("name", "personality", "language_style", "background", "behavior", "other_details"):
            if key in data:
                card[key] = data[key]
        card["updated_at"] = __import__("time").time()
        self._save()
        print(f"[角色卡] 更新: {card['name']} ({persona_id})")
        return True

    def delete_persona(self, persona_id: str) -> bool:
        """删除角色卡，同时清理所有引用"""
        if persona_id not in self.personas:
            return False
        name = self.personas[persona_id]["name"]
        del self.personas[persona_id]
        # 清理全局引用
        if self._global_persona_id == persona_id:
            self._global_persona_id = None
        # 清理逐用户引用
        to_del = [uid for uid, pid in self.user_persona_map.items() if pid == persona_id]
        for uid in to_del:
            del self.user_persona_map[uid]
        if self._persona_mode == "per_user" and not self.user_persona_map:
            self._persona_mode = "none"
        elif self._persona_mode == "global" and not self._global_persona_id:
            self._persona_mode = "none"
        self._save()
        print(f"[角色卡] 删除: {name} ({persona_id})")
        return True

    # ─── 查询 ──────────────────────────────────

    def get_all_personas(self) -> List[dict]:
        """返回所有角色卡列表"""
        return list(self.personas.values())

    def get_persona(self, persona_id: str) -> Optional[dict]:
        return self.personas.get(persona_id)

    def get_mode(self) -> str:
        return self._persona_mode

    def set_mode(self, mode: str):
        if mode in ("none", "global", "per_user"):
            self._persona_mode = mode
            self._save()

    def get_global_persona_id(self) -> Optional[str]:
        return self._global_persona_id

    def set_global_persona_id(self, pid: Optional[str]):
        self._global_persona_id = pid
        self._save()

    def get_user_persona_id(self, user_id: str) -> Optional[str]:
        return self.user_persona_map.get(user_id)

    def set_user_persona_id(self, user_id: str, pid: Optional[str]):
        if pid is None:
            self.user_persona_map.pop(user_id, None)
        else:
            self.user_persona_map[user_id] = pid
        self._save()

    def get_effective_persona_id(self, user_id: str) -> Optional[str]:
        """根据当前模式返回对 user_id 生效的角色卡 ID"""
        if self._persona_mode == "per_user":
            return self.user_persona_map.get(user_id)
        elif self._persona_mode == "global":
            return self._global_persona_id
        return None

    def get_effective_persona(self, user_id: str) -> Optional[dict]:
        pid = self.get_effective_persona_id(user_id)
        return self.personas.get(pid) if pid else None

    # ─── Prompt 构建 ───────────────────────────

    def build_persona_block(self, user_id: str) -> str:
        """构建角色卡描述文本块，供 system_prompt 注入"""
        persona = self.get_effective_persona(user_id)
        if not persona:
            return ""
        lines = []
        if persona.get("personality"):
            lines.append(f"【性格】{persona['personality']}")
        if persona.get("language_style"):
            lines.append(f"【语言风格】{persona['language_style']}")
        if persona.get("background"):
            lines.append(f"【背景设定】{persona['background']}")
        if persona.get("behavior"):
            lines.append(f"【行为习惯】{persona['behavior']}")
        if persona.get("other_details"):
            lines.append(f"【其他设定】{persona['other_details']}")
        if not lines:
            return ""
        block = "你现在扮演以下角色，请严格按照角色设定回复：\n"
        block += persona.get("name", "未命名角色") + "\n"
        block += "\n".join(lines)
        block += "\n\n请完全以这个角色的身份说话，不要跳出角色设定。"
        return block

    # ─── 导出给前端 ────────────────────────────

    def to_frontend_data(self, user_list: list) -> dict:
        """导出给前端渲染用的完整数据"""
        return {
            "personas": list(self.personas.values()),
            "user_persona_map": dict(self.user_persona_map),
            "global_persona_id": self._global_persona_id,
            "persona_mode": self._persona_mode,
            "users": user_list,
        }

    def apply_frontend_config(self, data: dict):
        """从前端提交的数据更新配置"""
        if "persona_mode" in data:
            self.set_mode(data["persona_mode"])
        if "global_persona_id" in data:
            self.set_global_persona_id(data.get("global_persona_id"))
        if "user_persona_map" in data:
            self.user_persona_map = data["user_persona_map"]
            self._save()
