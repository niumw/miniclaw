"""三层路由 — 反射/直觉/深思 + 推荐工具"""

from miniclaw.memory.store import MemoryStore
from miniclaw.memory.retriever import MemoryRetriever
from miniclaw.memory.store import Memory


class Router:
    """三层路由：反射 → 直觉 → 深思"""

    def __init__(self, store: MemoryStore, retriever: MemoryRetriever, intuition_confidence: float = 0.85):
        self.store = store
        self.retriever = retriever
        self.intuition_confidence = intuition_confidence

    def route(self, user_input: str) -> dict:
        """
        路由用户输入到合适的处理层。
        返回: {"layer": "reflex"|"intuition"|"deep", "rule": ..., "memories": ..., "tools": [...]}
        """
        # 层1：反射 — 匹配规则
        matched_rules = self.store.match_rule(user_input)
        if matched_rules:
            return {
                "layer": "reflex",
                "rule": matched_rules[0],
                "memories": [],
                "tools": [],
                "reason": f"匹配反射规则: {matched_rules[0]['pattern']}",
            }

        # 层2：直觉 — 检索记忆，高置信度直答
        memories = self.retriever.retrieve(user_input)
        if memories and self._should_direct_answer(user_input, memories):
            return {
                "layer": "intuition",
                "rule": None,
                "memories": memories,
                "tools": [],  # 直觉层不需要工具
                "reason": f"记忆命中{len(memories)}条，置信度足够",
            }

        # 层3：深思 — 需要模型推理，推荐工具
        tools = self._recommend_tools(user_input)

        return {
            "layer": "deep",
            "rule": None,
            "memories": memories,  # 仍然传入记忆作为参考
            "tools": tools,
            "reason": "需要模型推理",
        }

    def _should_direct_answer(self, question: str, memories: list[Memory]) -> bool:
        """判断记忆是否足够直接回答"""
        if not memories:
            return False

        # 高重要性记忆直接可用
        max_importance = max(m.importance for m in memories)
        if max_importance >= 0.8:
            return True

        # 已验证的记忆更可信
        verified = [m for m in memories if m.status == "verified"]
        if len(verified) >= 2:
            return True

        # 高 DIKW 层级的记忆更可靠
        high_level = [m for m in memories if m.dikw_level in ("knowledge", "wisdom")]
        if high_level and max_importance >= 0.6:
            return True

        return False

    def _recommend_tools(self, user_input: str) -> list[str]:
        """根据用户输入推荐可用的工具"""
        tools = []
        text = user_input.lower()

        # 文件操作关键词
        file_keywords = [
            "文件", "读取", "查看", "读", "写", "保存", "目录", "文件夹",
            "file", "read", "write", "list", "dir", "ls", "cat",
            "配置文件", "日志", "log", "config", "yaml", "json", "toml",
            "打开", "编辑", "修改", "创建",
        ]
        if any(k in text for k in file_keywords):
            tools.extend(["read_file", "write_file", "list_dir"])

        # URL/网页关键词
        url_keywords = ["url", "http", "网页", "网站", "链接", "访问"]
        if any(k in text for k in url_keywords):
            tools.append("fetch_url")

        # 记忆相关关键词
        memory_keywords = ["记住", "回忆", "之前", "以前", "上次", "记不记得", "忘了"]
        if any(k in text for k in memory_keywords):
            tools.extend(["search_memory", "save_memory"])

        # 默认：总是给 search_memory，因为模型可能需要查记忆
        if "search_memory" not in tools:
            tools.append("search_memory")

        return tools
