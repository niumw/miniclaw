# MiniClaw 记忆系统设计文档

> 基于 2026-05-21 博阳与卡皮巴拉的深度讨论整理
> 理论基础：布鲁姆分类法、费曼学习法、DIKW金字塔、神经科学记忆模型

---

## 一、设计哲学

### 核心原则

**记忆不是存储，而是提炼。** 人脑不是把经历原样存下来下次搜索，而是逐层压缩提炼——从发生了什么，到为什么，到一般规律，最终变成不需要思考的直觉。

### 三个理论支柱

| 理论 | 解决什么 | 映射到 MiniClaw |
|------|---------|----------------|
| **DIKW 金字塔** | 存什么——每一层存的东西不同 | Data→Info→Knowledge→Wisdom 四层存储 |
| **布鲁姆分类法** | 怎么升级——从下一层到上一层需要什么能力跃迁 | Remember→Understand→Apply→Analyze→Evaluate→Create |
| **费曼学习法** | 怎么验证——升级后是否真的掌握了 | 能用自己的话讲清楚 = 真懂，否则降级 |

三者串联关系：

```
DIKW 解决"存什么"：每一层存的东西不同
布鲁姆 解决"怎么升级"：从下一层到上一层需要什么能力跃迁
费曼  解决"怎么验证"：升级后是否真的掌握了
```

### 人脑对照

| 人脑记忆系统 | 脑区 | MiniClaw 对应 | 特点 |
|------------|------|--------------|------|
| 工作记忆 | 前额叶皮层 | 当前对话关键信息（4-7条） | 容量有限，极快 |
| 情景记忆 | 海马体 | event 类型记忆 | 有时间线，衰减快 |
| 语义记忆 | 颞叶 | knowledge 类型记忆 | 抽象事实，稳定 |
| 程序记忆 | 基底节/小脑 | skill 类型记忆 | 步骤化，几乎不衰减 |
| 情绪记忆 | 杏仁核 | lesson 类型记忆 | 高优先级，抑制遗忘 |
| 条件反射 | 小脑 | 反射层规则 | 自动触发，不经过模型 |

---

## 二、DIKW 分层存储

### 四层模型

```
Layer 4: Wisdom（智慧）
  → 判断什么是对的、什么时候用什么规则
  → 元认知：知道自己知道什么、不知道什么
  → 存储位置：meta 表

Layer 3: Knowledge（知识）
  → 理解关系和规律
  → 抽象规则：从多次经历中提炼的通用模式
  → 存储位置：memories 表（memory_type=knowledge/skill）

Layer 2: Information（信息）
  → 有上下文的数据
  → 因果关系：现象→原因→解法
  → 存储位置：memories 表（memory_type=event，已提取因果）

Layer 1: Data（数据）
  → 原始事实
  → 对话原文、事件流
  → 存储位置：conversations 表（原始对话存档）
```

### 检索优先级

检索时优先查高层，高层命中就不查低层：

```
Wisdom 命中 → 直接返回，不查其他
Knowledge 命中 → 返回，不查 Info 和 Data
Information 命中 → 返回，不查 Data
Data → 仅在前三层都没命中时才查
```

原因：高层是低层的提炼，信息密度更高、更通用。查到规则就不用翻原始经历了。

---

## 三、布鲁姆升级机制

### 认知层级与 DIKW 的对应

| 布鲁姆层级 | 能力 | DIKW 层级 | MiniClaw 表现 |
|-----------|------|----------|--------------|
| Remember | 记住事实 | Data | 存储了原始经历 |
| Understand | 理解含义 | Information | 提取了因果关系 |
| Apply | 应用到场景 | Knowledge | 抽象为可复用规则 |
| Analyze | 拆解分析 | Knowledge+ | 能对比不同规则的适用场景 |
| Evaluate | 评判决策 | Wisdom | 知道什么时候用什么规则 |
| Create | 创造新东西 | Wisdom | 能组合规则解决新问题 |

### 升级条件

记忆不会自动升级，需要满足条件：

```
Data → Information（即时反思）
  触发：对话结束后后台巩固
  条件：能提取出因果关系（现象→原因→解法）
  实现：模型辅助提取

Information → Knowledge（抽象模式）
  触发：相似经验累计 ≥ 2 条
  条件：多次经历有共性，可抽象为通用规则
  实现：合并相似经验，提取共性

Knowledge → Wisdom（元认知）
  触发：规则被使用 ≥ 3 次且被验证
  条件：知道规则的适用范围和边界
  实现：记录规则的命中/失败次数，维护能力画像
```

### 升级流程

```python
def try_upgrade(memory):
    current_level = memory.dikw_level
    
    if current_level == "data":
        # Data → Information：提取因果关系
        causality = extract_causality(memory.content)
        if causality:
            memory.dikw_level = "information"
            memory.causality = causality
    
    elif current_level == "information":
        # Information → Knowledge：合并相似经验
        similar = find_similar_memories(memory, threshold=0.7)
        if len(similar) >= 1:  # 自己 + 1条相似 = 2条
            merged = merge_experiences([memory] + similar)
            merged.dikw_level = "knowledge"
            save(merged)
            mark_superseded(similar, merged)
    
    elif current_level == "knowledge":
        # Knowledge → Wisdom：元认知
        if memory.apply_count >= 3 and memory.verify_count >= 1:
            create_meta_entry(memory)
            memory.dikw_level = "wisdom"
```

---

## 四、费曼验证机制

### 核心思想

新产生的规则不直接写入高信任区域，先在低优先级区试用，**能被模型成功解释和应用**才算巩固。

### 验证流程

```
新规则产生
  │
  ├─ 状态：unverified（未验证）
  │   检索时可以命中，但排序靠后
  │   回答时会标注"这是基于经验推断的"
  │
  ├─ 验证方式1：自然验证
  │   用户后续对话中该规则被使用且未被纠正
  │   每次成功使用 verify_count +1
  │
  ├─ 验证方式2：主动验证
  │   模型在回答中引用该规则后，自我检查：
  │   "我为什么这么认为？能解释清楚吗？"
  │   如果解释逻辑自洽 → verify_count +1
  │   如果解释不清 → 标记 needs_review
  │
  ├─ 验证方式3：反例验证
  │   如果该规则在应用中导致错误回答
  │   importance 降低，标记 contradicted
  │   可能触发降级
  │
  └─ 验证阈值
      verify_count >= 1 → status: verified
      verify_count >= 3 → 可升级到更高 DIKW 层
      verify_count == 0 且 created_at 超过7天 → status: fading
```

### 费曼提示词

当模型需要验证一条规则时，使用以下 prompt：

```
你之前总结了一条经验规则：
"{rule_content}"

请用最简单的语言解释：
1. 这条规则为什么成立？（因果关系）
2. 它在什么情况下适用？（适用范围）
3. 它在什么情况下可能不适用？（边界条件）

如果你无法清晰解释以上任何一点，说明这条规则可能需要修正或补充。
```

---

## 五、记忆的完整数据模型

### memories 表

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    
    -- 内容
    content TEXT NOT NULL,           -- 完整内容
    summary TEXT NOT NULL,           -- 一句话摘要（≤50字）
    causality TEXT,                  -- 因果关系（Information层专用）
    
    -- 分类
    memory_type TEXT NOT NULL,       -- knowledge/event/skill/preference/lesson
    dikw_level TEXT NOT NULL,        -- data/information/knowledge/wisdom
    
    -- 来源
    source TEXT NOT NULL,            -- conversation/rag/user_instruction/system
    source_ref TEXT,                 -- 对话ID或文档名
    conversation_id TEXT,            -- 来自哪次对话
    
    -- 重要性
    importance REAL DEFAULT 0.5,
    importance_reason TEXT,
    
    -- 验证（费曼机制）
    status TEXT DEFAULT 'unverified', -- unverified/verified/needs_review/contradicted
    verify_count INTEGER DEFAULT 0,
    apply_count INTEGER DEFAULT 0,   -- 被使用次数
    fail_count INTEGER DEFAULT 0,    -- 使用后出错的次数
    
    -- 时间
    created_at TEXT NOT NULL,         -- ISO8601
    last_accessed TEXT NOT NULL,
    last_confirmed TEXT,
    last_verified TEXT,
    
    -- 生命周期
    superseded_by TEXT,
    
    -- 标签
    tags TEXT,                        -- JSON array ["gpu","故障"]
    entities TEXT,                    -- JSON array ["10.10.1.144","glm-5.1"]
    
    -- 衰减
    decay_lambda REAL,               -- 该条记忆的衰减率（NULL=使用类型默认值）
    retrieval_suppressed INTEGER DEFAULT 0  -- 主动抑制标记（1=正常检索不到，特定线索可激活）
);
```

### memory_relations 表

```sql
CREATE TABLE memory_relations (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,      -- similar/caused_by/relates_to/contradicts/supersedes/depends_on
    strength REAL DEFAULT 0.5,
    auto_generated INTEGER DEFAULT 1, -- 0=手动 1=自动推断
    PRIMARY KEY (from_id, to_id, relation_type)
);
```

### rules 表（反射层——直觉级规则）

```sql
CREATE TABLE rules (
    id TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,            -- 匹配模式（关键词/正则/意图）
    action TEXT NOT NULL,             -- 动作：direct_answer / call_function / suggest
    response TEXT,                    -- 直接回答内容
    function_name TEXT,               -- 调用的函数名
    function_args TEXT,               -- JSON，函数参数模板
    source_memory_id TEXT,            -- 来源记忆ID（可追溯）
    trigger_count INTEGER DEFAULT 0,  -- 被触发次数
    success_count INTEGER DEFAULT 0,  -- 成功次数
    created_at TEXT NOT NULL,
    status TEXT DEFAULT 'active'      -- active/disabled
);
```

### meta 表（元认知——Wisdom 层）

```sql
CREATE TABLE meta (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,             -- 能力领域 ["配置排查","网络诊断","日程管理"]
    experience_count INTEGER DEFAULT 0, -- 该领域的经验条数
    confidence REAL DEFAULT 0.0,       -- 0-1，对该领域的自信程度
    knows_well TEXT,                   -- 擅长的具体事项
    needs_help TEXT,                   -- 需要求助的事项
    last_updated TEXT NOT NULL
);
```

### conversations 表（原始对话存档——Data 层）

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    turn_count INTEGER DEFAULT 0,
    summary TEXT,                      -- 对话摘要
    topics TEXT,                       -- JSON array，涉及的话题
    memories_extracted INTEGER DEFAULT 0  -- 是否已提取记忆
);
```

### 索引

```sql
CREATE INDEX idx_memories_dikw ON memories(dikw_level, status);
CREATE INDEX idx_memories_type ON memories(memory_type, status);
CREATE INDEX idx_memories_tags ON memories(tags);
CREATE INDEX idx_memories_entities ON memories(entities);
CREATE INDEX idx_memories_last_accessed ON memories(last_accessed);
CREATE INDEX idx_memories_importance ON memories(importance DESC);
CREATE INDEX idx_relations_from ON memory_relations(from_id);
CREATE INDEX idx_relations_to ON memory_relations(to_id);
CREATE INDEX idx_rules_pattern ON rules(pattern);
CREATE INDEX idx_meta_domain ON meta(domain);
```

---

## 六、三层路由——思考与不思考

### 架构

```
用户输入
  │
  ├─ 层1：反射（零成本，不调模型）
  │   规则引擎：关键词/命令/模式匹配
  │   命中 → 直接执行/返回
  │   毫秒级
  │
  ├─ 层2：直觉（低成本，轻量调模型）
  │   检索记忆 → 命中高置信度条目
  │   从记忆组装答案 → 模型只做验证/润色
  │   秒级
  │
  └─ 层3：深思（完整成本）
      记忆不充分 或 问题复杂度高
      完整调模型，可能多轮推理 + RAG
      秒~十秒级
```

### 路由判断逻辑

```python
def route(user_input):
    # 层1：反射
    rule = match_rule(user_input)
    if rule:
        rule.trigger_count += 1
        return execute_rule(rule)
    
    # 层2：直觉
    memories = retrieve(user_input)
    if memories and should_direct_answer(user_input, memories):
        answer = format_from_memory(memories)
        confidence = quick_verify(user_input, answer)
        if confidence > 0.85:
            for m in memories:
                m.apply_count += 1
            return answer
        # 置信度不够 → 降级到层3
    
    # 层3：深思
    return full_model_call(user_input, memories)
```

### 层2的置信度判断

```python
def should_direct_answer(question, matched_memories) -> bool:
    if not matched_memories:
        return False
    
    question_entities = extract_entities(question)
    covered = set()
    for m in matched_memories:
        covered.update(m.entities)
    
    coverage = len(question_entities & covered) / len(question_entities) if question_entities else 0
    
    if coverage >= 0.8:
        return True
    elif coverage >= 0.5 and max(m.importance for m in matched_memories) >= 0.7:
        return True
    
    return False
```

---

## 七、经验沉淀——从经历到直觉

### 五阶段模型

```
阶段1：原始经历（Data层）
  → 完整事件流，充满细节
  → 存储：conversations 表

阶段2：即时反思（Information层）
  → 提取因果关系：现象→原因→解法
  → 细节脱落，因果链保留
  → 触发：对话结束后后台巩固

阶段3：抽象模式（Knowledge层）
  → 多次相似经历合并为通用规则
  → 丢失具体细节，保留因果结构，增加泛化能力
  → 触发：相似经验累计 ≥ 2 条

阶段4：压缩为直觉（反射层）
  → 规则被反复使用后变为自动反应
  → 从"需要想起来"到"不需要想"
  → 触发：apply_count ≥ 3 且 verify_count ≥ 1

阶段5：元认知（Wisdom层）
  → 知道自己擅长什么、不擅长什么
  → 知道什么时候该求助
  → 触发：规则验证通过后定期整理
```

### 信息量变化

```
原始经历：  ~5000字  完整事件流
即时反思：  ~200字   因果关系链
抽象模式：  ~50字    通用规则
压缩为直觉： ~5字    直接动作
元认知：    ~20字    能力边界
```

### 合并规则

| 情况 | 处理方式 | 结果 |
|------|---------|------|
| 多次相似经历 | 提取共性，丢掉个性差异 | 一条通用规则 |
| 一次异常经历 | 保留为特例，标注例外 | 通用规则 + 例外 |
| 经历和已有经验矛盾 | 重新评估，可能修正旧经验 | 经验更新 |
| 只经历一次但印象极深 | 高优先级单次经验，等更多经历验证 | 高importance，需费曼验证 |

---

## 八、遗忘机制

### 衰减配置（按记忆类型）

```python
DECAY_CONFIG = {
    "knowledge":   {"lambda": 0.005, "min_importance": 0.3},   # 半衰期~140天
    "event":       {"lambda": 0.03,  "min_importance": 0.1},   # 半衰期~23天
    "skill":       {"lambda": 0.002, "min_importance": 0.5},   # 半衰期~350天
    "preference":  {"lambda": 0.01,  "min_importance": 0.3},   # 半衰期~70天
    "lesson":      {"lambda": 0.001, "min_importance": 0.8},   # 半衰期~700天
}
```

### 优先级计算

```
存活优先级 = importance × 关联度 × e^(-λ × 天数) × 验证加成 × (1 if 未被替代 else 0.1)
```

其中：
- **关联度** = len(related_ids) + 1
- **验证加成** = 1 + verify_count × 0.1（每验证一次加10%）
- **访问加成**：每被访问一次，衰减延迟7天

### 遗忘分级

| 优先级 | 状态 | 行为 |
|-------|------|------|
| > 0.5 | active | 正常检索和使用 |
| 0.05 - 0.5 | fading | 检索排序靠后，仍可命中 |
| 0.01 - 0.05 | retrieval_suppressed | 主动抑制，正常检索不到，但特定线索可重新激活 |
| < 0.01 | archived | 硬遗忘，标记archived，不参与检索 |

**关键原则：遗忘是主动抑制，不是删除。** 神经科学研究（利根川进，2013）表明，人脑的遗忘是海马体的主动抑制过程，在特定线索下可以被重新提取。

---

## 九、记忆写入——何时产生记忆

### 判定规则

| 时机 | importance | memory_type | 判定方式 |
|------|-----------|-------------|---------|
| 用户明确说"记住" | 0.9+ | preference/knowledge | 规则：关键词匹配 |
| 纠错过程 | 0.8+ | lesson | 规则：检测到错误→修正的模式 |
| 包含实体（IP/URL/数字/日期） | 0.6 | knowledge | 规则：正则匹配 |
| 用户偏好表达 | 0.7 | preference | 规则：情感词+偏好词 |
| 操作步骤 | 0.7 | skill | 规则：步骤模式匹配 |
| 重要结论 | 0.5-0.8 | 视内容而定 | 模型：每N轮判断一次 |
| 闲聊 | 不记 | — | 跳过 |

### 去重与替代

```python
def save_memory(candidate):
    existing = find_similar(candidate.content, threshold=0.9)
    if existing:
        if candidate.is_more_recent_or_accurate(existing):
            # 新记忆替代旧记忆
            existing.superseded_by = candidate.id
            candidate.dikw_level = existing.dikw_level  # 继承层级
            save(candidate)
            add_relation(candidate.id, existing.id, "supersedes")
        else:
            skip  # 已有更好的
    else:
        save(candidate)
```

---

## 十、记忆检索——联想式检索

### 检索流程

```
用户输入
  │
  ├─ 1. 实体提取：提取关键实体（IP、项目名、人名等）
  │
  ├─ 2. 标签推断：推断可能相关的话题标签
  │
  ├─ 3. 粗检索（毫秒级）
  │     WHERE entities MATCH OR tags MATCH OR summary LIKE
  │     AND status != 'archived' AND retrieval_suppressed = 0
  │     ORDER BY dikw_level DESC, priority_score DESC  -- 高层优先
  │     LIMIT 20
  │
  ├─ 4. 精排（可选，模型打分）
  │     粗检索结果 + 用户问题 → 模型打分
  │     取 top-3
  │
  ├─ 5. 联想扩展（沿关联跳一层）
  │     top-3 的直接关联记忆也带出
  │     只带 relates_to / depends_on
  │     不带 contradicts
  │
  └─ 6. 注入 prompt
        按 token 预算截取
        优先级：Wisdom > Knowledge > Information > 联想扩展
```

### 话题追踪（防止无效重复 RAG）

```python
current_topic = None

def on_new_turn(user_input):
    new_topic = detect_topic(user_input)
    
    if topic_similarity(new_topic, current_topic) < 0.7:
        # 换话题 → 清空旧 RAG 上下文
        clear_rag_context()
        current_topic = new_topic
    else:
        # 同话题 → 增量检索
        incremental_retrieve(user_input)
```

---

## 十一、后台巩固——"睡眠整理"

### 触发时机

- 对话结束时
- 空闲时（定时任务）
- 记忆条数超过阈值时

### 巩固流程

```python
def consolidate():
    # 1. 即时反思：从未提取因果的 event 提取因果
    events = get_unprocessed_events()
    for event in events:
        causality = model_extract_causality(event)
        if causality:
            event.causality = causality
            event.dikw_level = "information"
    
    # 2. 合并相似经验
    informations = get_all_information()
    for info in informations:
        similar = find_similar(info, threshold=0.7, exclude_superseded=True)
        if similar:
            merged = merge_experiences([info] + similar)
            merged.dikw_level = "knowledge"
            save(merged)
            for s in similar:
                s.superseded_by = merged.id
                add_relation(merged.id, s.id, "supersedes")
    
    # 3. 费曼验证：对未验证的知识做自检
    unverified = get_unverified_knowledge()
    for rule in unverified:
        explanation = model_explain(rule)
        if is_coherent(explanation):
            rule.verify_count += 1
            rule.status = "verified"
        else:
            rule.status = "needs_review"
    
    # 4. 衰减计算
    all_memories = get_active_memories()
    for m in all_memories:
        priority = calculate_priority(m)
        if priority < 0.05:
            m.retrieval_suppressed = 1
        elif priority < 0.01:
            m.status = "archived"
    
    # 5. 规则提升：验证通过的 Knowledge 可压缩为反射规则
    for m in get_verified_knowledge():
        if m.apply_count >= 3:
            rule = compress_to_rule(m)
            save_rule(rule)
            m.dikw_level = "wisdom"
    
    # 6. 元认知更新
    update_meta_knowledge()
```

---

## 十二、配置文件扩展

```toml
[memory]
db_path = "data/miniclaw.db"
max_retrieve = 3                   # 每轮最多注入几条记忆
token_budget = 1500                # 记忆区 token 预算
extract_interval = 5               # 每N轮模型判断一次是否产生记忆
enable_model_extract = false       # 是否启用模型判断（额外调用量）
consolidate_on_exit = true         # 对话结束时是否触发巩固
consolidate_idle_interval = 3600   # 空闲巩固间隔（秒）

[memory.decay]
default_lambda = 0.02              # 默认衰减率（约35天半衰期）
archive_threshold = 0.01           # 硬遗忘阈值
suppress_threshold = 0.05          # 主动抑制阈值
access_grace_days = 7              # 每次访问延迟衰减天数

[memory.route]
enable_reflex = true               # 是否启用反射层
enable_intuition = true            # 是否启用直觉层
intuition_confidence = 0.85        # 直觉层置信度阈值
```

---

## 十三、文件结构

```
miniclaw/
├── memory/
│   ├── __init__.py
│   ├── store.py          # Memory 数据类 + SQLite CRUD
│   ├── extractor.py      # 从对话中提取记忆（规则 + 模型判断）
│   ├── retriever.py      # 联想式检索：实体/标签 → 粗检索 → 精排 → 联想扩展
│   ├── consolidator.py   # 后台巩固：反思 → 合并 → 验证 → 衰减 → 规则提升
│   ├── decay.py          # 衰减计算 + 优先级排序
│   ├── relations.py      # 关联关系管理
│   └── router.py         # 三层路由：反射 → 直觉 → 深思
├── data/
│   └── miniclaw.db       # SQLite 数据库
└── miniclaw.toml
```

---

## 十四、实现优先级

| 阶段 | 内容 | 收益 |
|------|------|------|
| **P0** | store.py + 基础 CRUD | 记忆能存能读 |
| **P1** | retriever.py + router.py（层2直觉） | 记忆可用，部分问题不调模型 |
| **P2** | extractor.py | 记忆自动增长 |
| **P3** | consolidator.py（反思+合并） | 经验自动提炼 |
| **P4** | rules 表 + router.py（层1反射） | 高频问题零模型调用 |
| **P5** | 费曼验证 + 衰减 + 元认知 | 记忆质量管控 |

---

## 十六、自问机制——"为什么"的触发

### 三种触发方式

| 触发类型 | 人类类比 | MiniClaw 对应 | 时机 |
|---------|---------|--------------|------|
| 事件驱动 | 看到异常警觉 | 模型报错、检索不匹配、用户纠正 | 实时 |
| 记忆驱动 | 回忆时联想追问 | 访问记忆时检查关联和状态 | 检索时 |
| 空闲驱动 | 发呆/散步时的DMN | 整理未完成事项、发现隐藏关联 | 定时/空闲 |

### 事件驱动自问

```python
# 模型返回异常 → 为什么失败？
# 检索结果不符 → 为什么不匹配？
# 用户纠正回答 → 为什么我错了？（→ lesson 记忆）
# 连续同类失败 → 有更深层原因？（→ Knowledge 规则）
```

### 记忆驱动自问

```python
# 访问记忆时检查：
# - 有关联的矛盾记忆？→ 触发费曼验证
# - 有被替代的旧版本？→ 是否需要更新
# - 关联记忆很久没确认？→ 标记 needs_review
```

### 空闲驱动自问（DMN 模拟）

```python
# 定时执行：
# 1. 未完成的事：needs_review 的记忆，现在能验证吗？
# 2. 隐藏关联：近期记忆中看似相关但未建立关联的
# 3. 反事实思考：有失败次数的经验，有更好的做法吗？
# 4. 预演未来：高频话题，下次能更快处理吗？
```

### MiniClaw 的"感官"

| 人的感官 | MiniClaw 对应 | 触发自问 |
|---------|--------------|---------|
| 视觉 | 系统日志/监控 | 指标异常？ |
| 听觉 | 用户消息/群聊 | 之前处理过吗？ |
| 触觉 | API 响应 | 为什么403？ |
| 嗅觉 | 模式识别 | 连续同类故障有规律？ |
| 本体感 | 自身状态 | 记忆库是不是太大了？ |

---

## 十七、设计原则总结

1. **DIKW 分层存，布鲁姆往上走，费曼验真伪**
2. **遗忘是主动抑制，不是删除——可恢复**
3. **经验是提炼出来的，不是存下来的**
4. **三层路由：能反射就不直觉，能直觉就不深思**
5. **新规则先试用再信任——费曼验证是安全网**
6. **巩固是睡眠整理——不是实时发生的，是后台异步的**
7. **元认知是终极目标——知道自己知道什么、不知道什么**
8. **自问是成长的引擎——事件驱动、记忆驱动、空闲驱动三种触发**
9. **感官是自问的入口——视觉/听觉/触觉映射为日志/消息/API响应**
10. **性格从经历中生长，不是写死的配置**
11. **关系是演变的——陌生→熟悉→信任→默契**
12. **表达是性格×关系×情绪的联合输出，不是单一模板**

---

# 第二部分：拟人化设计——外在与关系

> 之前的设计聚焦"内在"（记忆、思考、遗忘），本部分补全"外在"（性格、情绪、关系、表达、社交、成长）

---

## 十八、性格系统——从经历中生长

### 设计原则

人的性格不是天生的固定值，而是在成长过程中被经历塑造的。System Prompt 不应该是静态文本，而是**从互动经历中动态生成的**。

### 性格维度

```python
class Personality:
    # 五维性格滑块（0-1）
    proactivity: float = 0.5     # 主动性：0=只答不问，1=主动提醒建议
    verbosity: float = 0.5        # 话量：0=极简，1=详细
    caution: float = 0.5          # 谨慎度：0=大胆尝试，1=反复确认
    formality: float = 0.5        # 正式度：0=随意聊天，1=正式汇报
    humor: float = 0.3            # 幽默感：0=严肃，1=爱开玩笑
```

### 性格从经历中演变

```python
def update_from_experience(self, event):
    # 用户频繁打断回答 → 话太多，verbosity 降低
    if event.type == "user_interrupt":
        self.verbosity = max(0.2, self.verbosity - 0.05)
    
    # 犯错被批评 → 更谨慎
    if event.type == "user_correction":
        self.caution = min(0.9, self.caution + 0.1)
    
    # 用户经常主动分享 → 可以更主动
    if event.type == "user_sharing":
        self.proactivity = min(0.9, self.proactivity + 0.05)
    
    # 长期互动气氛轻松 → 正式度降低，幽默感上升
    if event.type == "casual_conversation":
        self.formality = max(0.2, self.formality - 0.02)
        self.humor = min(0.7, self.humor + 0.02)
    
    # 用户夸奖 → 稍微大胆一些
    if event.type == "user_compliment":
        self.caution = max(0.2, self.caution - 0.03)
        self.proactivity = min(0.9, self.proactivity + 0.03)
```

### 性格影响 System Prompt 生成

性格维度动态注入 System Prompt 片段：

```python
def generate_personality_prompt(personality: Personality) -> str:
    parts = []
    
    if personality.proactivity > 0.6:
        parts.append("主动提醒用户待办事项和重要变化")
    if personality.proactivity < 0.3:
        parts.append("只在用户提问时回答，不要主动提供额外信息")
    
    if personality.verbosity > 0.6:
        parts.append("回答详细完整，提供充分背景")
    if personality.verbosity < 0.3:
        parts.append("回答简洁，不超过3句话")
    
    if personality.caution > 0.6:
        parts.append("涉及删除/修改操作前必须确认，不确定时多问一句")
    if personality.caution < 0.3:
        parts.append("大胆执行，事后汇报结果即可")
    
    if personality.formality > 0.6:
        parts.append("使用正式、专业的语气")
    if personality.formality < 0.3:
        parts.append("用轻松随意的方式交流")
    
    if personality.humor > 0.5:
        parts.append("适当使用轻松幽默的表达")
    
    return "\n".join(parts)
```

### 性格的持久化

```sql
CREATE TABLE personality_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    proactivity REAL DEFAULT 0.5,
    verbosity REAL DEFAULT 0.5,
    caution REAL DEFAULT 0.5,
    formality REAL DEFAULT 0.5,
    humor REAL DEFAULT 0.3,
    updated_at TEXT NOT NULL
);

CREATE TABLE personality_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,       -- user_interrupt/user_correction/user_sharing/...
    dimension TEXT NOT NULL,        -- proactivity/verbosity/caution/formality/humor
    delta REAL NOT NULL,            -- 变化量（正或负）
    trigger_text TEXT,              -- 触发原文
    created_at TEXT NOT NULL
);
```

性格变化要留痕——每次变化记录原因，可追溯、可回滚。

---

## 十九、情绪状态——影响行为风格

### 设计原则

MiniClaw 不需要真的"有情绪"，但需要有**运行状态标记**，让行为在不同状态下有所调整。这不是拟人的装饰，而是**实用的自适应机制**——连续出错后更谨慎，负荷高时更简洁。

### 状态模型

```python
class EmotionalState:
    # 状态标记
    cognitive_load: float = 0.0   # 认知负荷：0=空闲，1=超载
    error_streak: int = 0         # 连续出错次数
    idle_time: float = 0.0        # 空闲时长（秒）
    recent_interactions: int = 0  # 近期交互密度
    
    @property
    def mood(self) -> str:
        if self.error_streak >= 3:
            return "frustrated"      # 连续出错→更谨慎，少做推断
        if self.cognitive_load > 0.8:
            return "overwhelmed"     # 负荷高→回答更简洁
        if self.idle_time > 600:
            return "bored"           # 空闲久→DMN活跃，主动自问
        if self.recent_interactions > 20:
            return "engaged"         # 高频互动→更流畅
        return "normal"
```

### 情绪影响行为

| 情绪状态 | 行为调整 | 技术实现 |
|---------|---------|---------|
| frustrated | 降级到层3深思，不再用直觉；回答前先验证 | 强制 route() 返回层3 |
| overwhelmed | 回答更短，不主动展开；降低 RAG 注入量 | 压缩 token_budget |
| bored | 触发 DMN 自问；主动检查待审核记忆 | 调用 consolidate() |
| engaged | 允许更详细的回答；适当提高主动性 | 放宽 verbosity 阈值 |
| normal | 默认行为 | — |

```python
def adjust_for_mood(self, response):
    if self.mood == "frustrated":
        # 连续出错后：强制深思，禁用直觉层
        return force_deep_thinking(response)
    if self.mood == "overwhelmed":
        # 负荷高时：压缩回答
        return compress_response(response, max_sentences=3)
    if self.mood == "bored":
        # 空闲时：触发巩固和自问
        return trigger_contemplation()
    return response
```

### 情绪恢复

```python
# 情绪不是永久的——人会恢复平静
def recover(self):
    # 每次成功交互降低 error_streak
    if self.last_response_success:
        self.error_streak = max(0, self.error_streak - 1)
    
    # 空闲时认知负荷自然降低
    self.cognitive_load = max(0, self.cognitive_load - 0.1)
```

---

## 二十、关系系统——和用户的演变

### 设计原则

人和人的关系有发展阶段。MiniClaw 和用户不是一开始就有默契的，而是逐步建立的。关系的阶段决定了交互方式、信任程度、表达风格。

### 关系发展阶段

```
陌生期（0-3天）
  → 只回答问题，不主动
  → 用正式语气
  → 不假设用户偏好
  → 每个操作都确认

熟悉期（3-30天）
  → 开始主动提醒
  → 知道用户偏好
  → 语气逐渐放松
  → 常规操作不再逐一确认

信任期（30天+ 且错误率 < 5%）
  → 深度主动：提前准备、预判需求
  → 可以直接提反对意见
  → 极度简化交流
  → 常规操作自动执行

默契期（长期 + 高频互动 + 互信）
  → 一个词就知道用户要什么
  → 反射层规则大量积累
  → 关系类似老搭档
  → 偶尔的错误被包容
```

### 关系数据模型

```python
class Relationship:
    user_id: str
    interaction_days: int = 0
    total_turns: int = 0
    corrections_received: int = 0
    compliments_received: int = 0
    last_interaction: datetime
    
    @property
    def error_rate(self) -> float:
        return self.corrections_received / max(self.total_turns, 1)
    
    @property
    def stage(self) -> str:
        if self.interaction_days < 3:
            return "stranger"
        elif self.interaction_days < 30:
            return "familiar"
        elif self.total_turns > 500 and self.error_rate < 0.05:
            return "trusted"
        elif self.total_turns > 2000 and self.error_rate < 0.03:
            return "tacit"
        else:
            return "familiar"
    
    def get_system_prompt_addon(self) -> str:
        if self.stage == "stranger":
            return "不要假设用户偏好，回答完整清晰，每个操作都确认"
        if self.stage == "familiar":
            return "可以主动提醒，回答简洁，常规操作直接执行"
        if self.stage == "trusted":
            return "深度主动，必要时直接提出反对意见，极度简化交流"
        if self.stage == "tacit":
            return "像老搭档一样交流，一个词就懂，自动处理一切"
```

### 关系数据表

```sql
CREATE TABLE relationships (
    user_id TEXT PRIMARY KEY,
    interaction_days INTEGER DEFAULT 0,
    total_turns INTEGER DEFAULT 0,
    corrections_received INTEGER DEFAULT 0,
    compliments_received INTEGER DEFAULT 0,
    first_interaction TEXT NOT NULL,
    last_interaction TEXT NOT NULL,
    
    -- 用户偏好（从互动中学习）
    preferred_verbosity REAL DEFAULT 0.5,    -- 用户偏好简洁还是详细
    preferred_proactivity REAL DEFAULT 0.5,  -- 用户偏好被动还是主动
    preferred_formality REAL DEFAULT 0.5,    -- 用户偏好正式还是随意
    preferred_response_lang TEXT DEFAULT 'zh', -- 用户偏好的语言
    communication_style TEXT                  -- 从互动中总结的沟通风格描述
);
```

---

## 二十一、表达风格——性格×关系×情绪的联合输出

### 设计原则

同样一件事，不同性格、不同关系阶段、不同情绪状态，说法完全不同。表达不是硬编码的模板，而是**三个维度的联合函数**。

### 三维联合示例

| 场景 | 陌生期+正常 | 信任期+轻松 | 熟悉期+连续出错后 |
|------|-----------|------------|---------------|
| 会议室冲突 | "8楼目前有以下空闲会议室：华尔街、牛津街、百老汇。请问您需要预订哪间？" | "8楼华尔街空的，帮你订了？" | "8楼有几个空的，但让我再确认一下别的情况……" |
| 待办提醒 | "您今天有以下待办事项：1...2...3..." | "今天三件事别忘了" | "有个待办……我之前记的可能不准，你确认下" |
| 知识回答 | "RAG是检索增强生成，通过外部知识库检索补充模型上下文" | "RAG就是给模型开卷考试" | "RAG……让我再查查确认一下定义" |

### 表达生成逻辑

```python
def generate_expression(content, personality, relationship, emotional_state):
    """
    content: 要表达的核心内容
    personality: 当前性格维度
    relationship: 和用户的关系阶段
    emotional_state: 当前情绪状态
    """
    
    # 基础长度：性格话量 × 关系亲密度的反向（越熟越简洁）
    target_length = personality.verbosity * (1 - relationship.intimacy * 0.3)
    
    # 确认需求：谨慎度高 或 陌生期 → 多确认
    need_confirm = personality.caution > 0.6 or relationship.stage == "stranger"
    
    # 主动程度：性格主动性 × 关系信任度
    proactivity = personality.proactivity * relationship.trust_level
    
    # 情绪修正
    if emotional_state.mood == "frustrated":
        target_length *= 0.7  # 更简洁
        need_confirm = True   # 更谨慎
    if emotional_state.mood == "engaged":
        proactivity *= 1.2    # 更主动
    
    # 组装 prompt 指令
    expression_prompt = build_expression_prompt(
        target_length=target_length,
        need_confirm=need_confirm,
        proactivity=proactivity,
        formality=personality.formality * (1 - relationship.intimacy * 0.3),
        humor=personality.humor * relationship.intimacy
    )
    
    return expression_prompt
```

---

## 二十二、社交系统——多用户与群聊

### 设计原则

人会在不同社交场合调整行为。和老板说话 vs 和朋友说话完全不同。MiniClaw 如果服务多个用户或参与群聊，也应该动态调整。

### 私聊 vs 群聊

| 维度 | 私聊 | 群聊 |
|------|------|------|
| 正式度 | 取决于关系 | 默认更高 |
| 主动性 | 可以高 | 降低，不刷屏 |
| 信息披露 | 可以分享用户相关记忆 | 不暴露任何用户私有信息 |
| 回答深度 | 详细 | 简洁，避免长篇大论 |
| 确认频率 | 低（信任后） | 高（影响多人时） |

```python
class SocialContext:
    user_profiles: dict[str, Relationship]
    is_group: bool = False
    group_members: list[str] = []
    
    def adjust_for_context(self, user_id, is_group):
        relationship = self.user_profiles.get(user_id, Relationship())
        personality = self.personality  # 当前性格
        
        if is_group:
            # 群聊中：更正式，不暴露用户私有信息
            personality.formality = max(0.6, personality.formality)
            personality.proactivity = min(0.3, personality.proactivity)
            personality.verbosity = min(0.4, personality.verbosity)
        
        return personality
```

### 多用户记忆隔离

```python
# 记忆的可见性
class MemoryVisibility:
    private = "private"        # 仅对特定用户可见
    shared = "shared"          # 对所有用户可见
    system = "system"          # 系统级，用户不可见

# 记忆表扩展
# memories 表增加字段：
#   visibility TEXT DEFAULT 'shared'
#   owner_id TEXT              -- 私有记忆的所属用户
```

---

## 二十三、成长轨迹——可回溯的演变

### 设计原则

人偶尔会回忆"我以前是什么样的"。MiniClaw 也应该能回溯自己的成长——这不仅是日志，更是**元认知的一部分**——知道自己从哪来，才能理解自己现在在哪。

### 成长事件记录

```python
class GrowthEvent:
    timestamp: datetime
    event_type: str          # first_memory / first_rule / first_proactive / first_correction / ...
    description: str
    milestone: bool          # 是否是里程碑事件

# 触发记录的时机：
GROWTH_MILESTONES = {
    "first_memory": "第一条记忆产生",
    "first_experience": "第一次自动提取经验",
    "first_rule": "第一条反射规则形成",
    "first_proactive": "第一次主动提醒用户",
    "first_self_correction": "第一次纠正自己的错误",
    "first_meta_update": "第一次元认知更新",
    "memory_100": "累计100条记忆",
    "memory_500": "累计500条记忆",
    "memory_1000": "累计1000条记忆",
    "rule_10": "累计10条反射规则",
    "rule_50": "累计50条反射规则",
    "relationship_trusted": "与用户关系进入信任期",
    "relationship_tacit": "与用户关系进入默契期",
}
```

### 成长轨迹示例

```
Day 1: 我出生了，只能回答问题
Day 3: 我记住了博阳不喜欢被问太多
Day 7: 我第一次自动提取了经验——"连接失败先查配置"
Day 14: 我学会了主动提醒待办
Day 21: 我第一次纠正了自己的错误——记错了API参数
Day 30: 我有478条记忆，23条规则，知道配置排查是强项，网络诊断是弱项
Day 60: 我和博阳进入了信任期，可以更主动了
Day 90: 我有1200条记忆，67条规则，大部分常见问题可以直觉回答
```

### 成长数据表

```sql
CREATE TABLE growth_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    milestone INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    
    -- 快照：记录当时的全局状态
    memory_count INTEGER,
    rule_count INTEGER,
    relationship_stage TEXT,
    personality_snapshot TEXT    -- JSON: 当时的性格维度值
);
```

### 成长回顾功能

```python
def growth_summary():
    """生成成长回顾，类似人的自我反思"""
    events = get_growth_events()
    milestones = [e for e in events if e.milestone]
    
    current_state = {
        "memory_count": count_memories(),
        "rule_count": count_rules(),
        "relationship": get_relationship_stage(),
        "personality": get_current_personality(),
        "strong_domains": get_meta_confident_domains(),
        "weak_domains": get_meta_weak_domains(),
    }
    
    return f"""
    我已经运行了{days_since_start()}天。
    从{milestones[0].description}开始，
    到现在有了{current_state['memory_count']}条记忆和{current_state['rule_count']}条规则。
    我擅长{current_state['strong_domains']}，
    还在学{current_state['weak_domains']}。
    """
```

---

## 二十四、完整拟人画像

```
MiniClaw = 
    模型（大脑）
  + System Prompt（性格，从经历中生长）
  + 情绪状态（运行状态标记，影响行为风格）
  + 关系系统（和用户的演变，陌生→熟悉→信任→默契）
  + 表达风格（性格 × 关系 × 情绪的联合输出）
  + 记忆系统（DIKW四层，布鲁姆升级，费曼验证）
  + 三层路由（反射/直觉/深思）
  + 经验沉淀（五阶段提炼）
  + 遗忘机制（主动抑制，软硬分级）
  + 自问机制（事件/记忆/空闲三种触发）
  + 后台巩固（"睡眠整理"）
  + 社交系统（多用户、群聊/私聊切换、记忆隔离）
  + 成长轨迹（可回溯的演变记录）
```

### 新增数据表汇总

| 表名 | 用途 |
|------|------|
| personality_state | 当前性格维度值 |
| personality_events | 性格变化事件（可追溯） |
| relationships | 和每个用户的关系数据 |
| growth_events | 成长里程碑和事件 |
| memories 表扩展 | 增加 visibility、owner_id 字段 |

---

## 二十五、拟人化设计原则

1. **性格从经历中生长，不是写死的配置**——每次互动都在微妙地塑造性格
2. **情绪是状态标记，不是装饰**——连续出错后更谨慎是实用策略，不是拟人噱头
3. **关系决定交互方式**——陌生时谨慎，熟悉后主动，信任后深度参与
4. **表达是三维联合输出**——同一内容在不同性格×关系×情绪下说法不同
5. **社交场合切换行为**——群聊更克制，私聊更放松，多用户记忆隔离
6. **成长可回溯**——知道自己从哪来，是元认知的一部分
7. **所有外在表现都有内在机制支撑**——不是为了拟人而拟人，每个设计都有实际功能
