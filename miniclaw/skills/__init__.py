"""MiniClaw Skills — 可扩展的能力模块"""

from miniclaw.skills.http_fetch import HttpFetchSkill
from miniclaw.skills.file_io import FileIOSkill

__all__ = ["HttpFetchSkill", "FileIOSkill", "SKILL_REGISTRY"]

# Skill 注册表
SKILL_REGISTRY: dict[str, type] = {}

def register_skill(name: str, skill_cls: type):
    SKILL_REGISTRY[name] = skill_cls

def get_skill(name: str):
    return SKILL_REGISTRY.get(name)

# 自动注册
register_skill("http_fetch", HttpFetchSkill)
register_skill("file_io", FileIOSkill)
