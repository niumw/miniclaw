"""记忆观察者 — 监听 Harness 执行过程，自动提取记忆"""

from miniclaw.harness.plan import Plan, Step
from miniclaw.harness.executor import ExecutionResult
from miniclaw.harness.guardrails import GuardResult
from miniclaw.memory.store import MemoryStore, Memory
from miniclaw.memory.extractor import MemoryExtractor


class MemoryObserver:
    """观察 Harness 执行过程，自动提取记忆

    核心原则：
    - 失败比成功更值得记
    - 护栏事件优先级最高
    - 每个执行阶段自动触发记忆提取
    - 记忆反向影响规划（通过 Planner 检索）
    """

    def __init__(self, extractor: MemoryExtractor, store: MemoryStore):
        self.extractor = extractor
        self.store = store

    def on_step_complete(self, step: Step, plan: Plan):
        """步骤成功完成 → 从结果中提取记忆"""
        result_text = self._format_step_result(step, plan)
        # extractor.extract 接受 (user_input, assistant_reply) 两个参数
        memories = self.extractor.extract(plan.goal, result_text)

        for mem in memories:
            mem.importance = self._adjust_importance(mem, step, plan)
            mem.tags.append(f"harness:{plan.id}:{step.id}")
            self.store.save(mem)

    def on_step_failed(self, step: Step, plan: Plan, error: str):
        """步骤失败 → 强制生成失败记忆（失败默认高优先级）"""
        memory = Memory(
            content=f"执行'{step.description}'失败: {error}",
            summary=f"执行失败: {step.description[:40]}",
            memory_type="lesson",
            dikw_level="information",
            importance=0.8,
            entities=self.extractor._extract_entities(error, ""),
            tags=[f"harness:{plan.id}:{step.id}"],
        )
        self.store.save(memory)

    def on_replan(self, plan: Plan, failed_step: Step,
                  strategy: str, new_steps: list):
        """重规划 → 记录策略选择"""
        memory = Memory(
            content=f"步骤'{failed_step.description}'失败后，采用{strategy}策略继续",
            summary=f"重规划: {strategy}策略应对'{failed_step.description[:30]}'失败",
            memory_type="knowledge",
            dikw_level="knowledge",
            importance=0.7,
            entities=self.extractor._extract_entities(failed_step.description, ""),
            tags=[f"harness:{plan.id}:replan"],
        )
        self.store.save(memory)

    def on_guardrail_triggered(self, step: Step, guard_result: GuardResult):
        """护栏拦截 → 安全事件最高优先级"""
        memory = Memory(
            content=f"护栏拦截: {guard_result.reason}",
            summary=f"护栏拦截: {guard_result.reason[:40]}",
            memory_type="lesson",
            dikw_level="knowledge",
            importance=0.9,
            entities=[],
            tags=[f"harness:guardrail:{step.id}"],
        )
        self.store.save(memory)

    def on_plan_complete(self, result: ExecutionResult, plan: Plan):
        """计划完成 → 生成总结性记忆"""
        if result.success:
            summary = f"目标'{plan.goal}'成功完成，{result.steps_completed}步"
            importance = 0.6
        else:
            summary = f"目标'{plan.goal}'未完成，{result.steps_failed}步失败"
            importance = 0.8

        memory = Memory(
            content=summary,
            summary=summary[:50],
            memory_type="knowledge",
            dikw_level="knowledge",
            importance=importance,
            entities=self.extractor._extract_entities(plan.goal, ""),
            tags=[f"harness:{plan.id}:summary"],
        )
        self.store.save(memory)

    def _adjust_importance(self, memory: Memory, step: Step, plan: Plan) -> float:
        """根据执行上下文调整记忆优先级"""
        base = memory.importance

        # 失败步骤产生的记忆优先级更高
        if step.status == "failed":
            base = min(base + 0.2, 1.0)

        # 早期步骤（被后续步骤依赖）优先级更高
        dependent_ids = set()
        for s in plan.steps:
            dependent_ids.update(s.depends_on)
        if step.id in dependent_ids:
            base = min(base + 0.1, 1.0)

        # 包含实体（具体名称/地址/数值）的优先级更高
        if memory.entities:
            base = min(base + 0.1, 1.0)

        return base

    def _format_step_result(self, step: Step, plan: Plan) -> str:
        """将步骤结果格式化为文本，供提取器处理"""
        parts = [
            f"目标: {plan.goal}",
            f"步骤: {step.description}",
            f"状态: {step.status}",
        ]
        if step.result:
            parts.append(f"结果: {step.result}")
        if step.reflection:
            parts.append(f"反思: {step.reflection}")
        return "\n".join(parts)
