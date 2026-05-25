"""数据模型 — Plan / Step / Constraint"""

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Constraint:
    """执行约束"""
    kind: str          # permission / resource / safety / format
    rule: str          # 自然语言描述
    check: str         # "auto"（自动检查） / "confirm"（需用户确认）

    def __str__(self) -> str:
        return f"[{self.kind}] {self.rule} ({self.check})"


@dataclass
class Step:
    """一个执行步骤"""
    id: str                              # 步骤ID (如 "step_1")
    description: str                     # 这一步做什么（自然语言）
    tool: str | None = None              # 用什么工具（None=纯推理）
    args: dict = field(default_factory=dict)  # 工具参数模板（支持 {{step_N.xxx}} 引用）
    depends_on: list[str] = field(default_factory=list)  # 依赖哪些步骤
    status: str = "pending"              # pending / running / done / failed / skipped
    result: Any = None                   # 执行结果
    retry_count: int = 0                 # 已重试次数
    max_retries: int = 2                 # 最大重试次数
    reflection: str | None = None        # 失败时的反思记录
    needs_confirm: bool = False          # 是否需要用户确认

    def is_ready(self, completed_steps: set[str]) -> bool:
        """检查依赖是否满足"""
        return all(dep in completed_steps for dep in self.depends_on)

    def __str__(self) -> str:
        icon = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌", "skipped": "⏭️"}.get(self.status, "❓")
        return f"{icon} {self.id}: {self.description}"


@dataclass
class Plan:
    """一个执行计划"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    goal: str = ""                       # 用户给的原始目标
    steps: list[Step] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    status: str = "pending"              # pending / running / completed / failed / cancelled
    created_at: str = ""
    completed_at: str | None = None
    context: dict = field(default_factory=dict)  # 执行上下文（步骤间共享数据）

    def completed_steps(self) -> set[str]:
        """已完成的步骤ID集合"""
        return {s.id for s in self.steps if s.status == "done"}

    def failed_steps(self) -> list[Step]:
        """失败的步骤"""
        return [s for s in self.steps if s.status == "failed"]

    def summary(self) -> str:
        """计划摘要"""
        total = len(self.steps)
        done = len([s for s in self.steps if s.status == "done"])
        failed = len([s for s in self.steps if s.status == "failed"])
        skipped = len([s for s in self.steps if s.status == "skipped"])
        return f"{done}/{total} 完成 | {failed} 失败 | {skipped} 跳过"

    def __str__(self) -> str:
        lines = [f"📋 Plan [{self.id}]: {self.goal} ({self.status})"]
        for step in self.steps:
            lines.append(f"  {step}")
        for c in self.constraints:
            lines.append(f"  🔒 {c}")
        return "\n".join(lines)


@dataclass
class ExecutionResult:
    """一次执行的结果"""
    plan_id: str
    steps_total: int
    steps_completed: int
    steps_failed: int
    steps_skipped: int
    success: bool
    report: str           # 可读的执行报告
    lessons: list[str]    # 从执行中学到的经验
    duration_seconds: float


# ── 默认约束 ──

DEFAULT_CONSTRAINTS = [
    Constraint(kind="safety",    rule="不删除文件，只写新文件", check="auto"),
    Constraint(kind="safety",    rule="不执行 sudo 或 rm 命令", check="auto"),
    Constraint(kind="resource",  rule="单步执行不超过60秒", check="auto"),
    Constraint(kind="resource",  rule="单次计划不超过10步", check="auto"),
    Constraint(kind="permission", rule="发送消息/邮件等对外操作需确认", check="confirm"),
]
