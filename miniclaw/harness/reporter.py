"""报告器 — 执行报告 + 经验总结"""

from miniclaw.harness.plan import Plan
from miniclaw.harness.executor import ExecutionResult


class Reporter:
    """生成执行报告"""

    def report(self, result: ExecutionResult, plan: Plan) -> str:
        """生成可读的执行报告"""
        icon = "✅" if result.success else "❌"
        lines = [
            f"{icon} 执行报告: {plan.goal}",
            f"",
            f"📊 {result.steps_completed}/{result.steps_total} 步完成 | ⏱️ {result.duration_seconds:.1f}秒",
            f"",
            f"步骤详情:",
        ]

        for step in plan.steps:
            step_icon = {
                "done": "✅", "failed": "❌", "skipped": "⏭️", "pending": "⏳", "running": "🔄"
            }.get(step.status, "❓")

            lines.append(f"  {step_icon} {step.id}: {step.description}")

            if step.status == "failed" and step.reflection:
                lines.append(f"      反思: {step.reflection}")
            elif step.status == "skipped" and step.reflection:
                lines.append(f"      原因: {step.reflection}")

            if step.result and step.status == "done":
                result_str = str(step.result)
                if len(result_str) > 80:
                    result_str = result_str[:80] + "..."
                lines.append(f"      结果: {result_str}")

        # 约束触发记录
        triggered = [s for s in plan.steps if s.status == "skipped" and "护栏" in (s.reflection or "")]
        if triggered:
            lines.append(f"\n🔒 护栏触发:")
            for s in triggered:
                lines.append(f"  - {s.id}: {s.reflection}")

        # 失败统计
        if result.steps_failed > 0:
            lines.append(f"\n⚠️ 失败步骤: {result.steps_failed}")
            for s in plan.steps:
                if s.status == "failed":
                    lines.append(f"  - {s.id}: {s.reflection}")

        return "\n".join(lines)

    def brief(self, result: ExecutionResult, plan: Plan) -> str:
        """简短报告（一行摘要）"""
        icon = "✅" if result.success else "❌"
        return f"{icon} {plan.goal}: {result.steps_completed}/{result.steps_total}步, {result.duration_seconds:.0f}秒"
