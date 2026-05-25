"""记忆提取 — 从对话中判断是否产生记忆"""

import re
from miniclaw.memory.store import Memory


# 实体提取模式（顺序重要：长模式优先匹配，避免子串重复）
ENTITY_PATTERNS = [
    re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+'),                                        # URL
    re.compile(r'(?<![.\d\w-])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?(?![.\d])'),   # IP 或 IP:端口
    re.compile(r'[\w.-]+@[\w.-]+\.\w+'),                                                  # 邮箱
    re.compile(r'(?<![.\w-])([a-zA-Z][\w-]*(?:\.[\w-]+){1,}(?::\d+)?)'),                 # 域名:端口 (db.example.com:3306, api.openai.com)
    re.compile(r'(?:(?:工单号|编号|ID|id|订单号|序号)[:\s]*)(\d{3,})'),                      # 带前缀的纯数字ID
]

# 专有名词提取：从"记住XX是YY"模式中提取
NAME_VALUE_PATTERN = re.compile(
    r'(?:记住|叫|是|名为|名字)\s*[：:]*\s*([^\s，。,\.]{1,20})'
)

# 错误码提取：403, 404, 500, 502 等（不用 \b，中文语境不可靠）
ERROR_CODE_PATTERN = re.compile(r'(?:^|[\s,，。：:（(])([45]\d{2})(?:[\s,，。：:）).]|$)')

# 函数/接口名提取：下划线连接的英文词（如 batch_bind, room_ids）
FUNC_NAME_PATTERN = re.compile(r'\b[a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)+\b')

# 标签推断关键词
TAG_KEYWORDS = {
    "服务器": "服务器", "IP": "网络", "ip": "网络", "端口": "网络", "地址": "网络",
    "API": "API", "api": "API", "接口": "API",
    "密码": "认证", "token": "认证", "密钥": "认证", "key": "认证",
    "报错": "故障", "错误": "故障", "失败": "故障", "超时": "故障", "timeout": "故障",
    "配置": "配置", "设置": "配置", "config": "配置",
    "模型": "模型", "glm": "模型", "gpt": "模型",
    "会议室": "会议", "会议": "会议", "预订": "会议",
    "待办": "待办", "日程": "日程", "提醒": "日程",
}

# 常见停用词，函数名提取时排除
FUNC_STOPWORDS = {
    "the", "and", "for", "not", "are", "but", "all", "can", "had", "her",
    "was", "one", "our", "out", "has", "have", "this", "that", "with",
    "from", "they", "been", "said", "each", "which", "their", "will",
    "other", "than", "then", "them", "some", "would", "make", "like",
    "into", "time", "very", "when", "come", "could", "more", "over",
    "such", "after", "also", "did", "just", "about", "know", "take",
    "only", "what", "your", "there", "use", "how", "its", "may",
}


class MemoryExtractor:
    """从对话中提取记忆"""

    def extract(self, user_input: str, assistant_reply: str) -> list[Memory]:
        """
        分析一轮对话，判断是否需要产生记忆。
        返回需要保存的记忆列表。
        """
        candidates = []
        full_text = user_input + " " + assistant_reply

        # 规则1：用户明确要求记住
        if self._has_explicit_mark(user_input):
            mem = self._build_memory(
                user_input, assistant_reply,
                importance=0.9,
                memory_type="preference",
            )
            candidates.append(mem)

        # 规则2：包含实体信息
        entities = self._extract_entities(user_input, assistant_reply)
        if entities:
            mem = self._build_memory(
                user_input, assistant_reply,
                importance=0.6,
                memory_type="knowledge",
                entities=entities,
            )
            if candidates:
                candidates[0].entities = list(set(candidates[0].entities + entities))
                candidates[0].tags = list(set(candidates[0].tags + self._infer_tags(full_text)))
            else:
                candidates.append(mem)

        # 规则3：纠错过程
        if self._is_correction(user_input, assistant_reply):
            mem = self._build_memory(
                user_input, assistant_reply,
                importance=0.8,
                memory_type="lesson",
            )
            candidates.append(mem)

        # 规则4：偏好表达
        if self._is_preference(user_input):
            mem = self._build_memory(
                user_input, assistant_reply,
                importance=0.7,
                memory_type="preference",
            )
            if not candidates or candidates[0].memory_type != "preference":
                candidates.append(mem)

        # 规则5：有价值的陈述（包含实体或技术关键词，但不属于上述规则）
        # 即使有候选记忆，也检查是否遗漏了有价值的隐含信息
        if not candidates and self._is_valuable_statement(user_input):
            mem = self._build_memory(
                user_input, assistant_reply,
                importance=0.5,
                memory_type="knowledge",
            )
            candidates.append(mem)

        # 给所有候选补上 tags 和 entities
        for mem in candidates:
            if not mem.tags:
                mem.tags = self._infer_tags(full_text)
            if not mem.entities:
                mem.entities = self._extract_entities(user_input, assistant_reply)

        return candidates

    def _has_explicit_mark(self, text: str) -> bool:
        marks = ["记住", "别忘了", "记下来", "帮我记", "save", "remember", "记住这个"]
        return any(m in text.lower() for m in marks)

    def _extract_entities(self, user_input: str, assistant_reply: str) -> list[str]:
        """提取关键实体（扩展版：IP/URL/人名/错误码/函数名）"""
        full_text = user_input + " " + assistant_reply
        entities = []

        # 1. 结构化实体：IP、URL、邮箱、纯数字ID
        for pattern in ENTITY_PATTERNS:
            matches = pattern.findall(full_text)
            entities.extend(matches)

        # 2. 错误码：403, 404, 500, 502 等
        # 简单扫描：找4xx/5xx，排除IP地址和端口中的数字
        for match in re.finditer(r'[45]\d{2}', full_text):
            code = match.group()
            start = match.start()
            before = full_text[start-1:start] if start > 0 else ''
            after = full_text[start+3:start+4] if start+3 < len(full_text) else ''
            # 前后是数字的一部分（IP地址/端口），跳过
            if (before.isdigit() or after.isdigit() or before == '.' or after == '.' or after == ':'):
                continue
            entities.append(code)

        # 3. 函数/接口名：下划线连接的标识符（如 batch_bind, room_ids）
        func_names = FUNC_NAME_PATTERN.findall(full_text)
        entities.extend(func_names)

        # 4. 人名：从"叫/名为/名字是"后面提取2-4个中文字符
        cn_name = re.search(r'(?:叫|名为|名字[是为叫：:]*\s*)\s*([^\s，。,\.]{2,4})', user_input)
        if cn_name:
            name = cn_name.group(1)
            if all('\u4e00' <= c <= '\u9fff' for c in name) and name not in ("我的名字", "名字", "什么"):
                entities.append(name)

        return list(set(entities))

    def _infer_tags(self, text: str) -> list[str]:
        tags = set()
        for keyword, tag in TAG_KEYWORDS.items():
            if keyword in text:
                tags.add(tag)
        return list(tags)

    def _is_correction(self, user_input: str, assistant_reply: str) -> bool:
        correction_marks = ["不对", "不是", "错了", "应该是", "正确的是", "不对，", "不是，"]
        return any(m in user_input for m in correction_marks)

    def _is_preference(self, text: str) -> bool:
        pref_marks = ["我喜欢", "我不喜欢", "我偏好", "我习惯", "我希望你", "以后请", "以后都这样"]
        return any(m in text for m in pref_marks)

    def _is_valuable_statement(self, text: str) -> bool:
        """判断是否包含有价值的技术信息（但不属于其他规则）

        覆盖场景：
        1. 包含实体信息（IP/URL/域名等）
        2. 包含因果/技术关键词
        3. 包含隐性有价值陈述（"项目用XX写的"、"这个bug是因为XX"）
        4. 包含版本/环境/架构等技术描述
        """
        # 有实体信息
        entities = self._extract_entities(text, "")
        if entities:
            return True

        # 因果/技术关键词
        tech_keywords = [
            "因为", "导致", "原因是", "解决", "修复", "配置", "部署", "安装",
            "版本", "环境", "框架", "架构", "协议", "算法", "接口", "服务",
            "数据库", "缓存", "队列", "集群", "容器", "模块", "组件",
            "Python", "Java", "Go", "Rust", "Node", "React", "Vue",
            "Docker", "K8s", "Linux", "MySQL", "Redis", "Nginx",
        ]
        if any(k in text for k in tech_keywords):
            return True

        # 隐性有价值陈述模式
        implicit_patterns = [
            r'(?:项目|程序|服务|系统|代码)(?:用|是|基于|运行在|使用|写的|开发的)',
            r'(?:这个|那个)?(?:bug|问题|错误|故障)(?:是因为|由于|因为|根源)',
            r'(?:需要|必须|应该|最好)(?:用|使用|配置|设置|安装)',
            r'(?:服务器|机器|节点|集群)(?:是|有|在|运行)',
            r'(?:版本|环境|系统)(?:是|用|为|升级到)',
            r'(?:不支持|不兼容|不支持|无法)(?:\w+)',
        ]
        import re
        for pattern in implicit_patterns:
            if re.search(pattern, text):
                return True

        return False

    def _build_memory(
        self,
        user_input: str,
        assistant_reply: str,
        importance: float,
        memory_type: str,
        entities: list[str] | None = None,
    ) -> Memory:
        """构建一条记忆"""
        # Summary 优化：不再简单截断，保留完整关键信息
        summary = self._generate_summary(user_input, entities or [])

        content = f"用户: {user_input}\n助手: {assistant_reply}"

        return Memory(
            content=content,
            summary=summary,
            importance=importance,
            memory_type=memory_type,
            entities=entities or [],
        )

    def _generate_summary(self, user_input: str, entities: list[str]) -> str:
        """生成摘要：保留完整信息，不超过80字"""
        # 去掉"记住"等指令词，保留核心信息
        summary = user_input
        for prefix in ["记住", "别忘了", "记下来", "帮我记住"]:
            if summary.startswith(prefix):
                summary = summary[len(prefix):]
                break

        # 清理前后标点空格
        summary = summary.strip("，。,.！!？?：: ")

        # 如果有实体，确保 summary 包含实体信息
        # （正常情况下用户输入本身就包含实体）

        # 限制长度，但尽量不断在词中间
        if len(summary) > 80:
            # 尝试在标点处断开
            cut = summary[:80]
            last_punct = max(cut.rfind(p) for p in "，。,.！!？?；;：:")
            if last_punct > 40:
                summary = cut[:last_punct]
            else:
                summary = cut

        return summary
