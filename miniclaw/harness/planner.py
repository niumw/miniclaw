"""规划器 — 目标拆解 + 记忆检索 + 默认护栏"""

import json
from datetime import datetime, timezone

from miniclaw.harness.plan import Plan, Step, Constraint, DEFAULT_CONSTRAINTS
from miniclaw.memory.store import MemoryStore


# 规划 prompt 模板
PLAN_PROMPT = """你是一个任务规划器。请将以下目标拆解为可执行的步骤。

目标：{goal}
上下文：{context}
可用工具：{available_tools}
{memory_hints}

要求：
1. 每步必须有明确的描述
2. 标注步骤间的依赖关系（depends_on）
3. 标注哪些步骤需要用户确认（needs_confirm=true）
4. 步骤数量控制在3-10步
5. 每步指定使用的工具（tool），纯推理步骤 tool=null

输出严格JSON格式（不要包裹在代码块中）：
{{
  "steps": [
    {{
      "id": "step_1",
      "description": "步骤描述",
      "tool": "工具名或null",
      "args": {{}},
      "depends_on": [],
      "needs_confirm": false
    }}
  ],
  "constraints": [
    {{"kind": "safety", "rule": "约束描述", "check": "auto"}}
  ]
}}"""


class Planner:
    """规划器：目标 → 步骤列表"""

    def __init__(self, store: MemoryStore | None = None, tool_names: list[str] | None = None):
        self.store = store
        self.tool_names = tool_names or [
            "read_file", "write_file", "list_dir",
            "search_memory", "save_memory", "fetch_url",
        ]

    def plan(self, goal: str, context: dict | None = None) -> Plan:
        """
        将目标拆解为步骤。

        策略：
        1. 搜索相关记忆（历史教训 → 约束，已知事实 → 上下文）
        2. 模型拆解（调用模型生成步骤）
        3. 注入默认护栏
        4. 验证步骤依赖图无环
        """
        context = context or {}

        # 1. 检索记忆
        memory_constraints, memory_context = self._search_memory(goal)

        # 2. 合并上下文
        merged_context = {**context, **memory_context}

        # 3. 模型拆解
        plan = self._model_plan(goal, merged_context, memory_constraints)

        # 4. 注入默认护栏
        for c in DEFAULT_CONSTRAINTS:
            if not any(c.rule == existing.rule for existing in plan.constraints):
                plan.constraints.append(c)

        # 5. 验证
        self._validate_plan(plan)

        plan.status = "pending"
        plan.created_at = datetime.now(timezone.utc).isoformat()

        return plan

    def _search_memory(self, goal: str) -> tuple[list[Constraint], dict]:
        """搜索记忆，提取约束和上下文"""
        constraints = []
        context = {}

        if not self.store:
            return constraints, context

        related = self.store.search(query=goal, limit=5)
        for mem in related:
            if mem.memory_type == "lesson":
                constraints.append(
                    Constraint(kind="safety", rule=f"历史教训: {mem.content}", check="auto")
                )
            elif mem.memory_type == "knowledge":
                key = mem.entities[0] if mem.entities else "fact"
                context[f"已知_{key}"] = mem.content

        return constraints, context

    def _model_plan(self, goal: str, context: dict, memory_constraints: list[Constraint]) -> Plan:
        """调用模型生成计划"""
        from miniclaw.model import call_model_final

        memory_hints = ""
        if memory_constraints:
            memory_hints = "\n历史约束（必须遵守）：\n" + "\n".join(
                f"- {c.rule}" for c in memory_constraints
            )

        prompt = PLAN_PROMPT.format(
            goal=goal,
            context=json.dumps(context, ensure_ascii=False, indent=2) if context else "{}",
            available_tools=", ".join(self.tool_names),
            memory_hints=memory_hints,
        )

        try:
            # 用模型生成计划
            # 注意：这里需要调用方提供 model 配置，暂时用简化版
            raw = self._parse_plan_json(goal, context, memory_constraints)
            return raw
        except Exception:
            # 模型不可用时，降级为简单拆解
            return self._simple_plan(goal, context, memory_constraints)

    def _parse_plan_json(self, goal: str, context: dict, memory_constraints: list[Constraint]) -> Plan:
        """解析模型输出的计划 JSON（由调用方注入模型结果后使用）"""
        # 这个方法在 v0.6.0 中由 _model_plan 调用
        # 实际使用时，模型返回的 JSON 会在这里解析
        # 目前先用简单拆解作为默认
        return self._simple_plan(goal, context, memory_constraints)

    def _simple_plan(self, goal: str, context: dict, memory_constraints: list[Constraint]) -> Plan:
        """简单拆解策略（模型不可用时的降级方案）"""
        steps = [
            Step(id="step_1", description=f"理解目标: {goal}", tool=None, args={}),
            Step(id="step_2", description=f"执行: {goal}", tool=None, args={}, depends_on=["step_1"]),
            Step(id="step_3", description="验证结果", tool=None, args={}, depends_on=["step_2"]),
        ]

        return Plan(
            goal=goal,
            steps=steps,
            constraints=memory_constraints,
            context=context,
        )

    def plan_from_json(self, goal: str, json_str: str, context: dict | None = None) -> Plan:
        """从 JSON 字符串构建计划（模型输出解析入口）"""
        context = context or {}

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            import re
            match = re.search(r'\{[\s\S]*\}', json_str)
            if match:
                data = json.loads(match.group())
            else:
                raise

        steps = []
        for i, s in enumerate(data.get("steps", [])):
            steps.append(Step(
                id=s.get("id", f"step_{i+1}"),
                description=s.get("description", f"步骤{i+1}"),
                tool=s.get("tool"),
                args=s.get("args", {}),
                depends_on=s.get("depends_on", []),
                needs_confirm=s.get("needs_confirm", False),
            ))

        constraints = []
        for c in data.get("constraints", []):
            constraints.append(Constraint(
                kind=c.get("kind", "safety"),
                rule=c.get("rule", ""),
                check=c.get("check", "auto"),
            ))

        return Plan(
            goal=goal,
            steps=steps,
            constraints=constraints,
            context=context,
        )

    def _validate_plan(self, plan: Plan):
        """验证计划：检查依赖图无环、步骤数不超限"""
        # 检查步骤数
        if len(plan.steps) > 10:
            plan.steps = plan.steps[:10]

        # 检查依赖图无环（DFS）
        step_ids = {s.id for s in plan.steps}
        visited = set()
        in_stack = set()

        def dfs(step_id: str) -> bool:
            if step_id in in_stack:
                return True  # 有环
            if step_id in visited:
                return False
            visited.add(step_id)
            in_stack.add(step_id)
            step = next((s for s in plan.steps if s.id == step_id), None)
            if step:
                for dep in step.depends_on:
                    if dep in step_ids and dfs(dep):
                        # 移除环依赖
                        step.depends_on.remove(dep)
            in_stack.discard(step_id)
            return False

        for s in plan.steps:
            dfs(s.id)

        # 确保步骤 ID 唯一
        seen = set()
        for s in plan.steps:
            if s.id in seen:
                s.id = f"{s.id}_{len(seen)}"
            seen.add(s.id)
