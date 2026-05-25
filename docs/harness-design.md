# MiniClaw v0.6.0 架构设计：Harness 规划执行引擎

> 版本: v0.6.0-draft
> 作者: 水獭 & 卡皮巴拉
> 日期: 2026-05-25
> 状态: 设计中

---

## 一、设计目标

**一句话**：让 MiniClaw 从"你问我答"变成"你给我目标，我自己搞定"。

**量化目标**：
- 支持多步骤目标拆解和执行
- 单步失败后自动反思+重规划（不超过2次重试）
- 执行过程可观测（每步有状态、有结果）
- 约束护栏：执行前检查权限，执行中检查边界

---

## 二、核心架构

```
用户输入
  │
  ▼
┌─────────────────────────────────────────────────────┐
│                   Router（已有）                      │
│   反射 → 直觉 → 深思                                 │
│                                                     │
│   深思层判断：是否需要多步执行？                        │
│     · 单轮可答 → 直接回答（现有流程）                   │
│     · 需要多步 → 进入 Harness 流程                     │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                   Harness 引擎                       │
│                                                     │
│  ┌───────────┐                                      │
│  │ Planner   │  目标 → 步骤列表                      │
│  │ 规划器    │  注入约束条件                          │
│  └─────┬─────┘                                      │
│        │ Plan{steps, constraints}                   │
│        ▼                                            │
│  ┌───────────┐    ┌──────────────┐                  │
│  │ Executor  │    │ Guardrails   │                  │
│  │ 执行器    │◀──│ 护栏/约束     │                  │
│  │ 逐步执行  │    │ · 权限检查   │                  │
│  └─────┬─────┘    │ · 资源限制   │                  │
│        │          │ · 安全策略   │                  │
│        │          └──────────────┘                  │
│        ▼                                            │
│  ┌───────────┐                                      │
│  │ Replanner │  失败 → 反思 → 调整后续步骤            │
│  │ 重规划器  │  不是从头来，是在失败点调整              │
│  └─────┬─────┘                                      │
│        │                                            │
│        ▼                                            │
│  ┌───────────┐                                      │
│  │ Reporter  │  输出执行报告                         │
│  │ 报告器    │  记录经验到记忆系统                     │
│  └───────────┘                                      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 三、数据模型

### 3.1 Plan（计划）

```python
@dataclass
class Plan:
    """一个执行计划"""
    id: str                          # 唯一ID
    goal: str                        # 用户给的原始目标
    steps: list[Step]                # 拆解的步骤
    constraints: list[Constraint]    # 约束条件
    status: str                      # pending / running / completed / failed / cancelled
    created_at: str
    completed_at: str | None = None
    context: dict = field(default_factory=dict)  # 执行上下文（步骤间共享数据）
```

### 3.2 Step（步骤）

```python
@dataclass
class Step:
    """一个执行步骤"""
    id: str                          # 步骤ID (如 "step_1")
    description: str                 # 这一步做什么（自然语言）
    tool: str | None                 # 用什么工具（None=纯推理）
    args: dict                       # 工具参数模板（支持引用上一步结果）
    depends_on: list[str]            # 依赖哪些步骤
    status: str                      # pending / running / done / failed / skipped
    result: Any                      # 执行结果
    retry_count: int = 0             # 已重试次数
    max_retries: int = 2             # 最大重试次数
    reflection: str | None = None    # 失败时的反思记录
```

### 3.3 Constraint（约束）

```python
@dataclass
class Constraint:
    """执行约束"""
    kind: str          # permission / resource / safety / format
    rule: str          # 自然语言描述
    check: str         # 检查方式: "auto"（自动检查） / "confirm"（需用户确认）
```

### 3.4 ExecutionResult（执行结果）

```python
@dataclass
class ExecutionResult:
    """一次执行的结果"""
    plan_id: str
    steps_total: int
    steps_completed: int
    steps_failed: int
    steps_skipped: int
    success: bool
    report: str           # 可读的执行报告
    lessons: list[str]    # 从执行中学到的经验
    duration_seconds: float
```

---

## 四、模块设计

### 4.1 Planner（规划器）

**职责**：把用户目标拆解为可执行的步骤列表

**接口**：
```python
class Planner:
    def plan(self, goal: str, context: dict) -> Plan:
        """
        将目标拆解为步骤。
        
        策略：
        1. 判断目标复杂度（简单/中等/复杂）
        2. 根据复杂度决定步骤粒度
        3. 生成步骤 + 约束
        4. 注入默认护栏
        """
```

**拆解策略**：

| 复杂度 | 步骤数 | 示例 |
|--------|--------|------|
| 简单 | 1-3步 | "读取config.yaml" → [打开文件, 解析内容, 返回] |
| 中等 | 3-7步 | "部署服务" → [检查配置, 拉取镜像, 启动, 验证] |
| 复杂 | 7+步 | "集群NCCL测试" → [连通检查, 分发, 执行, 收集, 判定, 报告] |

**默认护栏（自动注入）**：
```python
DEFAULT_CONSTRAINTS = [
    Constraint(kind="safety",    rule="不删除文件，只用写新文件", check="auto"),
    Constraint(kind="safety",    rule="不执行sudo或rm命令", check="auto"),
    Constraint(kind="resource",  rule="单步执行不超过60秒", check="auto"),
    Constraint(kind="resource",  rule="单次计划不超过10步", check="auto"),
    Constraint(kind="permission", rule="发送消息/邮件等对外操作需确认", check="confirm"),
]
```

**实现方式**：通过模型推理拆解，prompt 模板：

```
你是一个任务规划器。请将以下目标拆解为可执行的步骤。

目标：{goal}
上下文：{context}
可用工具：{available_tools}

要求：
1. 每步必须有明确的输入和预期输出
2. 标注步骤间的依赖关系
3. 标注哪些步骤需要用户确认
4. 步骤数量控制在3-10步

输出JSON格式：
{ "steps": [...], "constraints": [...] }
```

### 4.2 Executor（执行器）

**职责**：逐步执行 Plan，每步检查约束

**接口**：
```python
class Executor:
    async def execute(self, plan: Plan) -> ExecutionResult:
        """
        执行计划。
        
        流程：
        for step in plan.steps:
            1. 检查依赖是否完成
            2. Guardrails.check(step) → 通过/阻断/需确认
            3. 执行步骤（调用工具或模型推理）
            4. 记录结果
            5. 如果失败 → Replanner.replan()
            6. 更新 plan.context（步骤间共享数据）
        """
```

**步骤间数据传递**：
```python
# 上一步的结果自动存入 context
plan.context["step_1_result"] = step_1.result

# 下一步的参数模板可以引用
step_2.args = {"path": "{{step_1_result.output_path}}"}
# 执行时替换为实际值
```

### 4.3 Guardrails（护栏）

**职责**：执行前/执行中检查约束

**接口**：
```python
class Guardrails:
    def check(self, step: Step, plan: Plan) -> GuardResult:
        """
        检查步骤是否允许执行。
        
        返回：
          allow  → 允许执行
          deny   → 阻断执行
          confirm → 需要用户确认
        """
    
    def validate_result(self, step: Step, result: Any) -> bool:
        """检查执行结果是否符合预期"""

@dataclass
class GuardResult:
    action: str          # allow / deny / confirm
    reason: str          # 原因
    suggestion: str      # 如果deny，建议怎么做
```

**自动检查规则**：

| kind | 检查内容 | 实现 |
|------|---------|------|
| safety | 工具参数不含 rm/sudo/drop | 关键词黑名单 |
| resource | 单步不超时 | 执行前估算 + 执行中超时 |
| permission | 对外操作确认 | 标记为 confirm 的操作暂停等用户 |
| format | 结果格式校验 | 预期格式 vs 实际格式 |

### 4.4 Replanner（重规划器）

**职责**：某步失败后，调整后续步骤

**接口**：
```python
class Replanner:
    def replan(self, plan: Plan, failed_step: Step) -> Plan:
        """
        失败后重规划。
        
        策略（按优先级）：
        1. 重试：同一策略重试（最多2次）
        2. 替代：换一个工具/方法完成同一目标
        3. 跳过：跳过失败步骤，继续后续
        4. 降级：降低目标完成度
        5. 求助：告诉用户无法完成，请求帮助
        """
```

**重规划策略矩阵**：

| 失败类型 | 重试 | 替代 | 跳过 | 降级 | 求助 |
|---------|------|------|------|------|------|
| 网络超时 | ✅ 1次 | ✅ | ⚠️ | ❌ | ❌ |
| 权限不足 | ❌ | ⚠️ | ❌ | ❌ | ✅ |
| 结果不符合 | ✅ 1次 | ✅ | ❌ | ⚠️ | ⚠️ |
| 工具不存在 | ❌ | ✅ | ⚠️ | ⚠️ | ✅ |
| 依赖失败 | ❌ | ⚠️ | ✅ | ✅ | ⚠️ |

### 4.5 Reporter（报告器）

**职责**：执行完毕后输出报告 + 保存经验

**接口**：
```python
class Reporter:
    def report(self, result: ExecutionResult) -> str:
        """生成可读的执行报告"""
    
    def save_lessons(self, result: ExecutionResult, store: MemoryStore):
        """将执行中的经验保存到记忆系统"""
```

**报告格式**：
```
📋 执行报告：{goal}

✅ 完成 4/5 步 | ⏱️ 32秒

步骤详情：
  1. ✅ 检查连通性 → 3个节点可达
  2. ✅ 分发测试程序 → 完成
  3. ⚠️ 执行测试 → 节点3超时，已跳过
     反思: 节点3可能网络波动，建议后续排查
  4. ✅ 收集结果 → 2/3节点数据
  5. ✅ 生成报告 → 已保存

💡 经验: 节点3在NCCL测试中超时（已保存到记忆）
```

---

## 五、与现有系统的集成

### 5.1 Router 扩展

```python
# router.py 扩展
class Router:
    def route(self, user_input: str) -> dict:
        # ... 现有三层路由 ...
        
        # 新增：深思层判断是否需要 Harness
        if layer == "deep":
            complexity = self._assess_complexity(user_input)
            if complexity == "simple":
                # 单轮推理即可（现有流程）
                return {"layer": "deep", "tools": [...], "harness": False}
            else:
                # 进入 Harness 流程
                return {"layer": "deep", "tools": [...], "harness": True}
```

### 5.2 复杂度评估

```python
def _assess_complexity(self, text: str) -> str:
    """评估任务复杂度"""
    # 简单标志：单步操作
    simple_signals = ["是什么", "多少", "有没有", "查询", "读取", "帮我看看"]
    # 复杂标志：多步操作
    complex_signals = ["部署", "测试", "分析", "整理", "帮我完成", "跑一下", "检查所有"]
    
    if any(s in text for s in complex_signals):
        return "complex"
    elif any(s in text for s in simple_signals):
        return "simple"
    else:
        return "medium"  # 中等，让模型判断
```

### 5.3 Chat 循环扩展

```python
# chat.py 扩展
async def _handle_input(self, user_input: str):
    route_result = self.router.route(user_input)
    
    if route_result.get("harness"):
        # Harness 流程
        plan = self.planner.plan(user_input, self.context)
        result = await self.executor.execute(plan)
        report = self.reporter.report(result)
        print(report)
        self.reporter.save_lessons(result, self.memory_store)
    else:
        # 现有流程
        await self._chat_with_tools(user_input)
```

---

## 六、文件结构

```
miniclaw/
├── __init__.py
├── __main__.py
├── chat.py            # 扩展：Harness 入口
├── config.py
├── model.py
├── harness/           # 🆕 新增
│   ├── __init__.py
│   ├── plan.py        # Plan + Step + Constraint 数据模型
│   ├── planner.py     # 规划器
│   ├── executor.py    # 执行器
│   ├── guardrails.py  # 护栏
│   ├── replanner.py   # 重规划器
│   └── reporter.py    # 报告器
├── memory/
│   ├── ...
│   └── router.py      # 扩展：复杂度评估 + harness 标记
└── skills/
    └── ...
```

---

## 七、关键设计决策

### Q1: Planner 用规则还是模型？

**决策：模型为主，规则兜底。**

- 模型负责拆解（理解语义，判断步骤）
- 规则负责护栏（安全约束，资源限制）
- 模型不可靠时降级为规则模板

### Q2: 步骤间怎么传递数据？

**决策：context 字典 + 模板引用。**

```python
# 执行 step_1 后
plan.context["step_1"] = {"output_path": "/tmp/result.txt", "count": 3}

# step_2 引用
step_2.args = {"input": "{{step_1.output_path}}"}

# 执行时替换
actual_args = resolve_templates(step_2.args, plan.context)
```

### Q3: 用户确认怎么实现？

**决策：暂停执行，等待用户输入。**

```
[Step 3] 需要发送邮件通知，确认？(y/n)
> y
[Step 3] ✅ 已发送
```

非交互模式（定时任务）下，confirm 类步骤自动跳过。

### Q4: 计划是否持久化？

**决策：v0.6.0 不持久化，v0.7.0 加入。**

- v0.6.0：计划在内存中，进程结束即消失
- v0.7.0：SQLite 持久化，支持断点续执行

---

## 八、v0.6.0 实现优先级

| 优先级 | 模块 | 工作量 | 说明 |
|--------|------|--------|------|
| P0 | `plan.py` 数据模型 | 2h | Plan/Step/Constraint 定义 |
| P0 | `planner.py` 规划器 | 4h | 模型拆解 + 默认护栏 |
| P0 | `executor.py` 执行器 | 4h | 步骤执行 + context 传递 |
| P1 | `guardrails.py` 护栏 | 3h | 安全检查 + 用户确认 |
| P1 | `replanner.py` 重规划 | 3h | 失败反思 + 策略选择 |
| P2 | `reporter.py` 报告器 | 2h | 报告格式 + 经验保存 |
| P1 | `router.py` 扩展 | 2h | 复杂度评估 + harness 标记 |
| P1 | `chat.py` 扩展 | 2h | Harness 入口 |

**总工作量估算**：~22h（约3个工作日）

---

## 九、测试用例

### 简单任务（不触发 Harness）
```
用户: 服务器IP是多少？
路由: 深思层 → 简单 → 直接回答
```

### 中等任务（触发 Harness，3-5步）
```
用户: 帮我读取config.yaml并检查有没有配置错误
Plan:
  Step 1: 读取 config.yaml → ✅
  Step 2: 解析配置项 → ✅
  Step 3: 检查常见错误模式 → ✅
  Step 4: 输出检查报告 → ✅
```

### 复杂任务（触发 Harness + 重规划）
```
用户: 跑一下集群的NCCL测试
Plan:
  Step 1: 检查连通性 → ✅ 3节点可达
  Step 2: 分发测试程序 → ❌ 节点3磁盘满
  Replan: 跳过节点3
  Step 2: 分发测试程序 → ✅ 2节点完成
  Step 3: 执行NCCL测试 → ✅
  Step 4: 收集结果 → ✅
  Step 5: 生成报告 → ✅
  
经验保存: "节点3磁盘满，NCCL测试无法分发"
```

---

## 十、与 v0.7.0 的衔接

v0.6.0 建立了 Harness 框架，v0.7.0 在此基础上加入：

- **Validator**：执行结果深度校验（不只是"成功/失败"，而是"符合预期吗"）
- **计划持久化**：SQLite 存储，支持断点续执行
- **性格影响**：规划风格随性格变化（谨慎型多加确认，主动型少确认）
- **经验复用**：相似目标自动复用历史 Plan 模板
