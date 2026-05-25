"""记忆检索 — 实体+标签+关键词多路召回"""

from miniclaw.memory.store import MemoryStore, Memory


class MemoryRetriever:
    """检索与当前输入相关的记忆"""

    def __init__(self, store: MemoryStore, max_results: int = 3, token_budget: int = 1500):
        self.store = store
        self.max_results = max_results
        self.token_budget = token_budget
        self.chars_per_token = 1.5

    def retrieve(self, user_input: str) -> list[Memory]:
        """
        检索与用户输入相关的记忆。
        策略：实体匹配 → 标签匹配 → 关键词匹配 → 去重排序
        """
        from miniclaw.memory.extractor import MemoryExtractor
        extractor = MemoryExtractor()

        entities = extractor._extract_entities(user_input, "")
        tags = extractor._infer_tags(user_input)

        candidates: list[Memory] = []
        seen_ids: set[str] = set()

        def add_candidate(mem: Memory):
            if mem.id not in seen_ids:
                candidates.append(mem)
                seen_ids.add(mem.id)

        # 1. 实体精确匹配（最高优先级）
        for entity in entities:
            results = self.store.search(query=entity, limit=5)
            for r in results:
                add_candidate(r)

        # 2. 标签匹配
        if tags:
            results = self.store.search(tags=tags, limit=5)
            for r in results:
                add_candidate(r)

        # 3. 关键词模糊匹配
        keywords = self._extract_keywords(user_input)
        for kw in keywords:
            results = self.store.search(query=kw, limit=3)
            for r in results:
                add_candidate(r)

        # 3.5 特殊：问"名字/叫/谁"时额外搜实体中的中文名
        name_triggers = {"名字", "叫什么", "是谁", "谁", "姓名"}
        if any(t in user_input for t in name_triggers):
            # 搜索所有 preference 类型记忆（人名通常存为 preference）
            results = self.store.search(memory_type="preference", limit=5)
            for r in results:
                if r.entities:
                    add_candidate(r)

        # 4. 联想扩展：沿关联跳一层（取 top 候选的关联记忆）
        if candidates:
            top_for_assoc = sorted(candidates, key=lambda m: m.importance, reverse=True)[:2]
            for mem in top_for_assoc:
                related = self.store.get_related_memories(mem.id, relation_type="relates_to")
                for r in related:
                    add_candidate(r)

        # 按 DIKW 层级 + 重要性排序
        dikw_order = {"wisdom": 4, "knowledge": 3, "information": 2, "data": 1}
        candidates.sort(
            key=lambda m: (dikw_order.get(m.dikw_level, 2), m.importance),
            reverse=True,
        )
        selected = candidates[: self.max_results]

        # 更新访问计数
        for mem in selected:
            self.store.touch(mem.id)

        return selected

    def format_for_prompt(self, memories: list[Memory]) -> str:
        """将记忆格式化为可注入 prompt 的文本"""
        if not memories:
            return ""

        parts = ["[相关记忆]"]
        total_chars = 0
        max_chars = int(self.token_budget * self.chars_per_token)

        for mem in memories:
            # 精简格式：只放摘要和关键实体，不放完整 content
            entry = f"- ({mem.memory_type}/{mem.dikw_level}) {mem.summary}"
            if mem.entities:
                entry += f" [{', '.join(mem.entities[:5])}]"

            if total_chars + len(entry) > max_chars:
                break

            parts.append(entry)
            total_chars += len(entry)

        return "\n".join(parts) if len(parts) > 1 else ""

    def _extract_keywords(self, text: str) -> list[str]:
        """从用户输入中提取关键词"""
        stop_words = {"的", "了", "是", "在", "我", "你", "他", "她", "它", "这", "那", "有", "不",
                       "也", "都", "就", "要", "会", "可以", "能", "请", "帮", "给", "让", "和",
                       "与", "或", "但", "而", "如果", "因为", "所以", "什么", "怎么", "如何",
                       "为什么", "哪", "哪个", "多少", "几", "吗", "呢", "吧", "啊", "嗯",
                       "了没", "一下", "一个", "什么", "是不是", "有没有"}

        # 中文分词：用滑动窗口提取 2-4 字的词组
        import re
        keywords = []

        # 先用标点和英文空格分割
        segments = re.split(r'[\s,，。.!！?？、；;：:""\'\'（）()【】\[\]{}<>《》/\\|@#$%^&*+=~`]+', text)

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            # 纯英文/数字/符号段，直接作为关键词
            if re.match(r'^[a-zA-Z0-9_.\-:/]+$', seg):
                if seg not in stop_words and len(seg) >= 2:
                    keywords.append(seg)
                continue
            # 中文段：滑动窗口提取 2-4 字词组
            if len(seg) <= 4 and seg not in stop_words:
                keywords.append(seg)
            else:
                # 提取 2-4 字的 n-gram，过滤停用词
                for n in (4, 3, 2):
                    for i in range(len(seg) - n + 1):
                        gram = seg[i:i+n]
                        if gram not in stop_words and not all(c in stop_words for c in gram):
                            keywords.append(gram)

        # 去重，保留顺序
        seen = set()
        unique = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                unique.append(k)

        return unique[:8]
