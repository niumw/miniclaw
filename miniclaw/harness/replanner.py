"""重规划器 — 失败后反思 + 策略选择"""

from miniclaw.harness.plan import Plan, Step


# 重规划策略矩阵
STRATEGY_MATRIX = {
    "network_timeout":  ["retry_once", "alternative", "skip"],
    "permission_denied": ["ask_user", "alternative"],
    "result_mismatch":  ["retry_once", "alternative", "downgrade"],
    "tool_not_found":   ["alternative", "skip", "downgrade"],
    "dependency_failed": ["skip", "downgrade", "alternative"],
    "unknown":          ["retry_once", "alternative", "ask_user"],
}


class Replanner:
    """失败后重规划"""

    def replan(self, plan: Plan, failed_step: Step) -> dict:
        """
        失败后重规划。
        
        策略（按优先级）：
        1. retry: 同一策略重试（最多2次）
        2. alternative: 换一个工具/方法完成同一目标
        3. skip: 跳过失败步骤，继续后续
        4. downgrade: 降低目标完成度
        5. ask_user: 告诉用户无法完成，请求帮助
        
        返回: {"_strategy": "策略名", "_new_steps": [...], ...}
        """
        error_type = self._classify_error(failed_step.reflection or "")
        strategies = STRATEGY_MATRIX.get(error_type, STRATEGY_MATRIX["unknown"])

        for strategy in strategies:
            result = self._apply_strategy(strategy, plan, failed_step)
            if result:
                return result

        # 所有策略都失败，求助于用户
        return {
            "_strategy": "ask_user",
            "_new_steps": [],
            "message": f"步骤 '{failed_step.description}' 失败，无法自动恢复。错误: {failed_step.reflection}",
        }

    def _classify_error(self, error: str) -> str:
        """分类错误类型"""
        error_lower = error.lower()

        if any(kw in error_lower for kw in ["timeout", "timed out", "超时", "connection"]):
            return "network_timeout"
        if any(kw in error_lower for kw in ["permission", "权限", "denied", "forbidden"]):
            return "permission_denied"
        if any(kw in error_lower for kw in ["not found", "不存在", "missing", "no such"]):
            return "tool_not_found"
        if any(kw in error_lower for kw in ["mismatch", "不符合", "invalid", "验证失败"]):
            return "result_mismatch"
        if any(kw in error_lower for kw in ["依赖", "dependency", "depends"]):
            return "dependency_failed"

        return "unknown"

    def _apply_strategy(self, strategy: str, plan: Plan, failed_step: Step) -> dict | None:
        """应用重规划策略"""
        if strategy == "retry_once":
            # 重置步骤状态为 pending，下次会重新执行
            new_step = Step(
                id=failed_step.id,
                description=failed_step.description,
                tool=failed_step.tool,
                args=failed_step.args,
                depends_on=failed_step.depends_on,
                status="pending",
                retry_count=failed_step.retry_count,
                max_retries=failed_step.max_retries,
                needs_confirm=failed_step.needs_confirm,
            )
            return {
                "_strategy": "retry_once",
                "_new_steps": [new_step],
                "message": f"重试步骤 '{failed_step.description}'",
            }

        elif strategy == "alternative":
            # 尝试替代工具
            alt_tool = self._find_alternative_tool(failed_step.tool)
            if alt_tool:
                new_step = Step(
                    id=failed_step.id,
                    description=f"{failed_step.description} (替代方案: {alt_tool})",
                    tool=alt_tool,
                    args=failed_step.args,
                    depends_on=failed_step.depends_on,
                    status="pending",
                    retry_count=failed_step.retry_count,
                    max_retries=failed_step.max_retries,
                )
                return {
                    "_strategy": "alternative",
                    "_new_steps": [new_step],
                    "message": f"使用替代工具 '{alt_tool}' 代替 '{failed_step.tool}'",
                }
            return None

        elif strategy == "skip":
            # 跳过失败步骤
            new_step = Step(
                id=failed_step.id,
                description=failed_step.description,
                tool=failed_step.tool,
                args=failed_step.args,
                depends_on=failed_step.depends_on,
                status="skipped",
                reflection=f"跳过: {failed_step.reflection}",
            )
            return {
                "_strategy": "skip",
                "_new_steps": [new_step],
                "message": f"跳过步骤 '{failed_step.description}'",
            }

        elif strategy == "downgrade":
            # 降低目标
            new_step = Step(
                id=failed_step.id,
                description=f"{failed_step.description} (降级: 仅完成部分)",
                tool=failed_step.tool,
                args=failed_step.args,
                depends_on=failed_step.depends_on,
                status="pending",
            )
            return {
                "_strategy": "downgrade",
                "_new_steps": [new_step],
                "message": f"降级执行 '{failed_step.description}'",
            }

        elif strategy == "ask_user":
            return {
                "_strategy": "ask_user",
                "_new_steps": [],
                "message": f"无法自动恢复步骤 '{failed_step.description}'，需要用户帮助",
            }

        return None

    def _find_alternative_tool(self, tool: str | None) -> str | None:
        """查找替代工具"""
        alternatives = {
            "fetch_url": "read_file",      # URL 不可用时尝试本地文件
            "read_file": "fetch_url",      # 文件不可用时尝试 URL
            "write_file": None,            # 写文件没有替代
            "list_dir": "read_file",       # 列目录失败时尝试读文件
            "search_memory": None,         # 搜索记忆没有替代
            "save_memory": None,           # 保存记忆没有替代
        }
        if tool:
            return alternatives.get(tool)
        return None
