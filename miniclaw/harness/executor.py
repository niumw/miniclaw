"""执行器 — 逐步执行 Plan + 步骤间数据传递"""

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from miniclaw.harness.plan import Plan, Step, ExecutionResult
from miniclaw.harness.guardrails import Guardrails
from miniclaw.harness.replanner import Replanner
from miniclaw.harness.memory_observer import MemoryObserver


class Executor:
    """逐步执行计划，每步检查约束"""

    def __init__(
        self,
        guardrails: Guardrails,
        replanner: Replanner,
        observer: MemoryObserver | None = None,
        tool_executors: dict[str, Callable] | None = None,
        confirm_fn: Callable[[str], bool] | None = None,
    ):
        self.guardrails = guardrails
        self.replanner = replanner
        self.observer = observer
        self.tool_executors = tool_executors or {}
        self.confirm_fn = confirm_fn or self._default_confirm

    async def execute(self, plan: Plan) -> "ExecutionResult":
        """执行计划"""
        plan.status = "running"
        start_time = time.time()

        for step in plan.steps:
            if plan.status != "running":
                break

            # 1. 检查依赖
            if not step.is_ready(plan.completed_steps()):
                step.status = "skipped"
                continue

            # 2. 护栏检查
            guard_result = self.guardrails.check(step, plan)
            if guard_result.action == "deny":
                step.status = "skipped"
                step.reflection = guard_result.reason
                if self.observer:
                    self.observer.on_guardrail_triggered(step, guard_result)
                continue
            elif guard_result.action == "confirm":
                if not self.confirm_fn(guard_result.reason):
                    step.status = "skipped"
                    step.reflection = "用户拒绝确认"
                    if self.observer:
                        self.observer.on_guardrail_triggered(step, guard_result)
                    continue

            # 3. 解析参数模板
            resolved_args = self._resolve_args(step.args, plan.context)

            # 4. 执行步骤
            step.status = "running"
            try:
                result = await self._execute_step(step, resolved_args, plan)
                step.status = "done"
                step.result = result

                # 存入 context 供后续步骤引用
                plan.context[step.id] = self._to_context_value(result)

                if self.observer:
                    self.observer.on_step_complete(step, plan)

            except Exception as e:
                step.status = "failed"
                step.reflection = str(e)

                if self.observer:
                    self.observer.on_step_failed(step, plan, str(e))

                # 5. 尝试重规划
                if step.retry_count < step.max_retries:
                    step.retry_count += 1
                    new_plan = self.replanner.replan(plan, step)

                    if self.observer:
                        self.observer.on_replan(
                            plan, step,
                            new_plan.get("_strategy", "retry"),
                            new_plan.get("_new_steps", []),
                        )

                    # 将新步骤加入计划
                    self._merge_replanned_steps(plan, new_plan)
                else:
                    # 重试次数用完，标记计划失败
                    plan.status = "failed"

        # 计算结果
        if plan.status == "running":
            plan.status = "completed"

        plan.completed_at = datetime.now(timezone.utc).isoformat()
        duration = time.time() - start_time

        result = ExecutionResult(
            plan_id=plan.id,
            steps_total=len(plan.steps),
            steps_completed=len([s for s in plan.steps if s.status == "done"]),
            steps_failed=len([s for s in plan.steps if s.status == "failed"]),
            steps_skipped=len([s for s in plan.steps if s.status == "skipped"]),
            success=plan.status == "completed",
            report="",
            lessons=[],
            duration_seconds=duration,
        )

        if self.observer:
            self.observer.on_plan_complete(result, plan)

        return result

    async def _execute_step(self, step: Step, args: dict, plan: Plan) -> Any:
        """执行单个步骤"""
        if step.tool and step.tool in self.tool_executors:
            # 调用工具
            executor = self.tool_executors[step.tool]
            result = executor(args)
            return result
        else:
            # 纯推理步骤 — 返回描述
            return {"description": step.description, "type": "reasoning"}

    def _resolve_args(self, args: dict, context: dict) -> dict:
        """解析参数模板，替换 {{step_N.xxx}} 引用"""
        if not args:
            return args

        resolved = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_template(value, context)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_args(value, context)
            else:
                resolved[key] = value
        return resolved

    def _resolve_template(self, template: str, context: dict) -> str:
        """替换模板变量 {{step_id.field}}"""
        def replacer(match):
            path = match.group(1)
            parts = path.split(".")
            value = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, match.group(0))
                else:
                    return match.group(0)
            return str(value)

        return re.sub(r'\{\{(\w+(?:\.\w+)*)\}\}', replacer, template)

    def _to_context_value(self, result: Any) -> dict:
        """将执行结果转为 context 字典"""
        if isinstance(result, dict):
            return result
        return {"output": result}

    def _merge_replanned_steps(self, plan: Plan, replan_result: dict):
        """将重规划结果合并到计划中"""
        new_steps = replan_result.get("_new_steps", [])
        for new_step in new_steps:
            # 找到合适的插入位置（失败步骤之后）
            failed_idx = next(
                (i for i, s in enumerate(plan.steps) if s.id == new_step.id),
                len(plan.steps),
            )
            if failed_idx < len(plan.steps):
                # 替换失败步骤
                plan.steps[failed_idx] = new_step
            else:
                # 追加新步骤
                plan.steps.append(new_step)

    @staticmethod
    def _default_confirm(reason: str) -> bool:
        """默认确认函数（交互模式下询问用户）"""
        try:
            response = input(f"⚠️ {reason} (y/n): ").strip().lower()
            return response in ("y", "yes", "是")
        except EOFError:
            return False
