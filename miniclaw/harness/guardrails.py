"""护栏 — 执行前/执行中约束检查"""

from dataclasses import dataclass

from miniclaw.harness.plan import Step, Plan, Constraint


# 安全关键词黑名单
SAFETY_BLACKLIST = [
    "rm -rf", "sudo rm", "del /f", "format ", "mkfs.",
    "dd if=", "> /dev/sd", "shutdown", "reboot",
    "DROP TABLE", "DELETE FROM", "TRUNCATE",
]

# 危险路径模式
DANGEROUS_PATHS = [
    "/etc/passwd", "/etc/shadow", "/etc/sudoers",
    "/boot/", "/sys/", "/proc/",
    "C:\\Windows\\System32",
]


@dataclass
class GuardResult:
    """护栏检查结果"""
    action: str          # allow / deny / confirm
    reason: str          # 原因
    suggestion: str = "" # 如果deny，建议怎么做

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    def __str__(self) -> str:
        icons = {"allow": "✅", "deny": "🚫", "confirm": "⚠️"}
        return f"{icons.get(self.action, '❓')} {self.action}: {self.reason}"


class Guardrails:
    """执行护栏：检查步骤是否允许执行"""

    def check(self, step: Step, plan: Plan) -> GuardResult:
        """
        检查步骤是否允许执行。
        
        检查顺序：
        1. 约束检查（plan.constraints）
        2. 安全检查（关键词黑名单）
        3. 资源检查（步骤数限制）
        4. 权限检查（需确认的操作）
        """
        # 1. 约束检查
        for constraint in plan.constraints:
            result = self._check_constraint(step, constraint)
            if not result.allowed:
                return result

        # 2. 安全检查
        safety_result = self._check_safety(step)
        if not safety_result.allowed:
            return safety_result

        # 3. 用户确认检查
        if step.needs_confirm:
            return GuardResult(
                action="confirm",
                reason=f"步骤 '{step.description}' 需要用户确认",
                suggestion="等待用户确认后继续",
            )

        # 4. 约束中的 confirm 类型
        for constraint in plan.constraints:
            if constraint.check == "confirm":
                result = self._check_needs_confirm(step, constraint)
                if result.action == "confirm":
                    return result

        return GuardResult(action="allow", reason="通过所有检查")

    def validate_result(self, step: Step, result) -> bool:
        """检查执行结果是否符合基本预期"""
        result_str = str(result)
        # 不应该包含错误信息
        error_signals = ["Error", "Exception", "Traceback", "Permission denied"]
        return not any(sig in result_str for sig in error_signals)

    def _check_constraint(self, step: Step, constraint: Constraint) -> GuardResult:
        """检查单条约束"""
        if constraint.kind == "safety" and constraint.check == "auto":
            # 安全约束：检查步骤描述和参数
            step_text = f"{step.description} {step.args}".lower()
            rule_text = constraint.rule.lower()

            # "不删除" 约束
            if "不删除" in rule_text or "不执行" in rule_text:
                for pattern in SAFETY_BLACKLIST:
                    if pattern.lower() in step_text:
                        return GuardResult(
                            action="deny",
                            reason=f"违反约束: {constraint.rule} (检测到 '{pattern}')",
                            suggestion="使用写新文件代替删除旧文件",
                        )

            # "不执行sudo" 约束
            if "sudo" in rule_text:
                if "sudo" in step_text:
                    return GuardResult(
                        action="deny",
                        reason=f"违反约束: {constraint.rule}",
                        suggestion="寻找不需要 sudo 的替代方案",
                    )

        return GuardResult(action="allow", reason="约束检查通过")

    def _check_safety(self, step: Step) -> GuardResult:
        """安全检查：关键词黑名单 + 危险路径"""
        step_text = f"{step.description} {step.args}"

        # 关键词检查
        for pattern in SAFETY_BLACKLIST:
            if pattern.lower() in step_text.lower():
                return GuardResult(
                    action="deny",
                    reason=f"检测到危险操作: '{pattern}'",
                    suggestion="这是一个危险操作，请寻找更安全的替代方案",
                )

        # 危险路径检查
        for path in DANGEROUS_PATHS:
            if path.lower() in step_text.lower():
                return GuardResult(
                    action="deny",
                    reason=f"检测到危险路径: '{path}'",
                    suggestion="不要操作关键系统文件",
                )

        return GuardResult(action="allow", reason="安全检查通过")

    def _check_needs_confirm(self, step: Step, constraint: Constraint) -> GuardResult:
        """检查是否需要用户确认"""
        step_text = f"{step.description} {step.args}".lower()

        if "对外" in constraint.rule or "发送" in constraint.rule:
            if any(kw in step_text for kw in ["发送", "邮件", "通知", "消息", "send", "mail", "notify"]):
                return GuardResult(
                    action="confirm",
                    reason=f"步骤可能涉及对外操作: {constraint.rule}",
                    suggestion="等待用户确认",
                )

        return GuardResult(action="allow", reason="无需确认")
