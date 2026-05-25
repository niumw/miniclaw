"""衰减计算 — 遗忘机制"""

import math
from datetime import datetime, timezone
from miniclaw.memory.store import Memory


# 按记忆类型的衰减配置
DECAY_CONFIG = {
    "knowledge":   {"lambda": 0.005, "min_importance": 0.3},   # 半衰期~140天
    "event":       {"lambda": 0.03,  "min_importance": 0.1},   # 半衰期~23天
    "skill":       {"lambda": 0.002, "min_importance": 0.5},   # 半衰期~350天
    "preference":  {"lambda": 0.01,  "min_importance": 0.3},   # 半衰期~70天
    "lesson":      {"lambda": 0.001, "min_importance": 0.8},   # 半衰期~700天
}

DEFAULT_DECAY = {"lambda": 0.02, "min_importance": 0.2}  # 默认约35天半衰期

# 阈值
SUPPRESS_THRESHOLD = 0.05   # 低于此值 → 软遗忘（检索抑制）
ARCHIVE_THRESHOLD = 0.01    # 低于此值 → 硬遗忘（归档）


def calculate_priority(memory: Memory) -> float:
    """计算记忆的存活优先级"""
    now = datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(memory.last_accessed)
    except (ValueError, TypeError):
        last = now
    days_since = max((now - last).days, 0)

    # 衰减配置
    cfg = DECAY_CONFIG.get(memory.memory_type, DEFAULT_DECAY)
    decay_lambda = cfg["lambda"]

    # 时间衰减
    time_decay = math.exp(-decay_lambda * days_since)

    # 访问加成：每被访问一次，延迟7天衰减
    access_grace = min(memory.access_count * 7, 60)  # 最多延迟60天
    effective_days = max(days_since - access_grace, 0)
    time_decay = math.exp(-decay_lambda * effective_days)

    # 关联加成：暂时用 access_count 近似（正式版应查 relations 表）
    relatedness = min(memory.access_count + 1, 10) / 10  # 0.1 ~ 1.0

    # 验证加成
    verify_bonus = 1 + memory.verify_count * 0.1

    # 被替代的记忆大幅降权
    superseded_factor = 0.1 if memory.superseded_by else 1.0

    priority = (
        memory.importance
        * relatedness
        * time_decay
        * verify_bonus
        * superseded_factor
    )

    # min_importance 约束：优先级不低于该类型的最小重要性
    # （防止高价值记忆被过度衰减）
    min_imp = cfg.get("min_importance", 0.1)
    if memory.importance >= min_imp and priority < min_imp * 0.5:
        priority = min_imp * 0.5

    return priority


def should_suppress(memory: Memory) -> bool:
    """是否应该软遗忘（检索抑制）"""
    return calculate_priority(memory) < SUPPRESS_THRESHOLD


def should_archive(memory: Memory) -> bool:
    """是否应该硬遗忘（归档）"""
    return calculate_priority(memory) < ARCHIVE_THRESHOLD


def get_decay_status(memory: Memory) -> str:
    """获取记忆的衰减状态描述"""
    priority = calculate_priority(memory)
    if priority > 0.5:
        return "active"
    elif priority > 0.1:
        return "fading"
    elif priority > ARCHIVE_THRESHOLD:
        return "suppressed"
    else:
        return "archived"
