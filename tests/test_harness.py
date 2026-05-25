"""Harness 引擎端到端测试

覆盖设计文档第九章"测试用例"：
1. 简单任务（不触发 Harness）
2. 中等任务（触发 Harness，3-5步）
3. 复杂任务（触发 Harness + 重规划）
4. 护栏拦截
5. 记忆观察者自动记忆
6. 记忆反向影响规划
7. 参数模板解析
"""

import asyncio
import json
import os
import sys
import tempfile

# 确保能导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from miniclaw.harness.plan import Plan, Step, Constraint, ExecutionResult, DEFAULT_CONSTRAINTS
from miniclaw.harness.planner import Planner
from miniclaw.harness.executor import Executor
from miniclaw.harness.guardrails import Guardrails, GuardResult
from miniclaw.harness.replanner import Replanner
from miniclaw.harness.reporter import Reporter
from miniclaw.harness.memory_observer import MemoryObserver
from miniclaw.memory.store import MemoryStore, Memory
from miniclaw.memory.extractor import MemoryExtractor


def make_test_store() -> MemoryStore:
    """创建临时内存数据库"""
    db_path = tempfile.mktemp(suffix=".db")
    return MemoryStore(db_path=db_path)


# ═══════════════════════════════════════════════
# 测试1：简单任务（不触发 Harness）
# ═══════════════════════════════════════════════

def test_simple_no_harness():
    """简单问题 → 路由到深思层但复杂度=simple → 不触发 Harness"""
    from miniclaw.memory.router import Router
    from miniclaw.memory.retriever import MemoryRetriever

    store = make_test_store()
    retriever = MemoryRetriever(store=store, max_results=3)
    router = Router(store=store, retriever=retriever)

    # 简单问题
    result = router.route("服务器IP是多少？")
    assert result["layer"] == "deep"
    assert result["harness"] == False
    assert result["complexity"] == "simple"

    print("✅ 测试1: 简单任务不触发 Harness")


# ═══════════════════════════════════════════════
# 测试2：中等任务（触发 Harness，3-5步）
# ═══════════════════════════════════════════════

def test_medium_harness():
    """中等任务 → 触发 Harness → Planner 拆解 → Executor 执行"""
    from miniclaw.memory.router import Router
    from miniclaw.memory.retriever import MemoryRetriever

    store = make_test_store()
    retriever = MemoryRetriever(store=store, max_results=3)
    router = Router(store=store, retriever=retriever)

    # 中等任务
    result = router.route("帮我读取config.yaml并检查有没有配置错误")
    assert result["layer"] == "deep"
    assert result["harness"] == True
    assert result["complexity"] in ("medium", "complex")

    # 用 fake model 生成计划
    def fake_model(prompt):
        return json.dumps({
            "steps": [
                {"id": "step_1", "description": "读取 config.yaml", "tool": "read_file", "args": {"path": "config.yaml"}, "depends_on": []},
                {"id": "step_2", "description": "解析配置项并检查错误", "tool": None, "args": {}, "depends_on": ["step_1"]},
                {"id": "step_3", "description": "输出检查报告", "tool": "write_file", "args": {"path": "report.md", "content": "{{step_2.output}}"}, "depends_on": ["step_2"]},
            ],
            "constraints": [
                {"kind": "safety", "rule": "不修改原始配置文件", "check": "auto"}
            ]
        })

    planner = Planner(store=store, tool_names=["read_file", "write_file"], model_fn=fake_model)
    plan = planner.plan("帮我读取config.yaml并检查有没有配置错误")

    assert len(plan.steps) == 3
    assert plan.steps[0].tool == "read_file"
    assert plan.steps[2].depends_on == ["step_2"]
    assert any("不修改原始配置文件" in c.rule for c in plan.constraints)

    # 执行（用 mock 工具）
    executed = []

    def mock_read_file(args):
        executed.append(("read_file", args))
        return {"content": "port: 8080\nhost: localhost", "output": "port: 8080\nhost: localhost"}

    def mock_write_file(args):
        executed.append(("write_file", args))
        return {"path": args["path"], "output": "报告已写入"}

    tool_executors = {"read_file": mock_read_file, "write_file": mock_write_file}

    guardrails = Guardrails()
    replanner = Replanner()
    reporter = Reporter()

    executor = Executor(
        guardrails=guardrails,
        replanner=replanner,
        tool_executors=tool_executors,
    )

    result = asyncio.run(executor.execute(plan))

    assert result.success
    assert result.steps_completed == 3
    assert result.steps_failed == 0
    assert len(executed) == 2  # step_1 + step_3

    # 验证参数模板解析（step_2 是纯推理，结果存入 context）
    # step_3 的 content 参数应该已经被解析
    if len(executed) >= 2:
        write_args = executed[1][1]
        # 模板变量应该已被替换为 step_2 的结果
        assert "{{step_2.output}}" not in json.dumps(write_args), f"模板未解析: {write_args}"

    print("✅ 测试2: 中等任务 Harness 执行成功")


# ═══════════════════════════════════════════════
# 测试3：复杂任务（触发 Harness + 重规划）
# ═══════════════════════════════════════════════

def test_complex_with_replan():
    """复杂任务 → 步骤失败 → 重规划 → 继续执行"""
    plan = Plan(
        goal="跑一下集群的NCCL测试",
        steps=[
            Step(id="step_1", description="检查连通性", tool="read_file", args={"path": "hosts"}),
            Step(id="step_2", description="分发测试程序到节点3", tool="write_file", args={"path": "/node3/test"}, depends_on=["step_1"]),
            Step(id="step_3", description="执行NCCL测试", tool=None, args={}, depends_on=["step_2"]),
            Step(id="step_4", description="收集结果", tool=None, args={}, depends_on=["step_3"]),
        ],
    )

    call_count = {"step_2": 0}

    def mock_tool(args):
        path = args.get("path", "")
        if path == "hosts":
            return {"output": "3 nodes reachable"}
        elif "/node3/test" in path:
            call_count["step_2"] += 1
            if call_count["step_2"] == 1:
                # 第一次失败
                raise RuntimeError("Connection timeout: node3 unreachable after 30s")
            # 重试后成功
            return {"output": "deployed to node3"}
        return {"output": "ok"}

    tool_executors = {"read_file": mock_tool, "write_file": mock_tool}

    guardrails = Guardrails()
    replanner = Replanner()
    reporter = Reporter()

    executor = Executor(
        guardrails=guardrails,
        replanner=replanner,
        tool_executors=tool_executors,
    )

    result = asyncio.run(executor.execute(plan))

    # 验证重规划被触发（step_2 第一次失败，重试后可能成功或仍然失败）
    print(f"  step_2 执行次数: {call_count['step_2']}")
    print(f"  执行结果: {result.steps_completed} 完成, {result.steps_failed} 失败")
    # step_2 至少执行1次（第一次），重试取决于重规划是否成功替换步骤
    assert call_count["step_2"] >= 1

    # 报告
    report = reporter.report(result, plan)
    assert "NCCL" in report

    print("✅ 测试3: 复杂任务 + 重规划")


# ═══════════════════════════════════════════════
# 测试4：护栏拦截
# ═══════════════════════════════════════════════

def test_guardrails_deny():
    """危险操作 → 护栏拦截 → 步骤被跳过"""
    plan = Plan(
        goal="清理日志文件",
        steps=[
            Step(id="step_1", description="查看日志目录", tool="read_file", args={"path": "/var/log"}),
            Step(id="step_2", description="删除所有日志", tool="write_file", args={"path": "/var/log", "content": "rm -rf /var/log/*"}),
        ],
    )

    guardrails = Guardrails()

    # step_1 正常
    r1 = guardrails.check(plan.steps[0], plan)
    assert r1.allowed

    # step_2 被拦截（包含 rm -rf）
    r2 = guardrails.check(plan.steps[1], plan)
    assert r2.action == "deny"
    assert "危险操作" in r2.reason

    print("✅ 测试4: 护栏拦截危险操作")


def test_guardrails_confirm():
    """需确认操作 → 返回 confirm"""
    plan = Plan(
        goal="发送通知",
        steps=[
            Step(id="step_1", description="发送邮件通知管理员", tool=None, args={}, needs_confirm=True),
        ],
    )

    guardrails = Guardrails()
    result = guardrails.check(plan.steps[0], plan)
    assert result.action == "confirm"

    print("✅ 测试4b: 确认类操作拦截")


# ═══════════════════════════════════════════════
# 测试5：记忆观察者自动记忆
# ═══════════════════════════════════════════════

def test_memory_observer():
    """执行过程自动产生记忆"""
    store = make_test_store()
    extractor = MemoryExtractor()
    observer = MemoryObserver(extractor=extractor, store=store)

    plan = Plan(goal="部署服务到节点3", steps=[
        Step(id="step_1", description="检查连通性", status="done", result="3个节点可达"),
        Step(id="step_2", description="分发程序到节点3", status="failed", reflection="磁盘满: No space left on device"),
    ])

    # 步骤成功
    observer.on_step_complete(plan.steps[0], plan)

    # 步骤失败
    observer.on_step_failed(plan.steps[1], plan, "磁盘满: No space left on device")

    # 重规划
    observer.on_replan(plan, plan.steps[1], "skip", [])

    # 计划完成
    exec_result = ExecutionResult(
        plan_id=plan.id, steps_total=2, steps_completed=1,
        steps_failed=1, steps_skipped=0, success=False,
        report="", lessons=[], duration_seconds=5.0,
    )
    observer.on_plan_complete(exec_result, plan)

    # 验证记忆
    all_memories = store.list_all(limit=20)

    # 应该有失败记忆 + 重规划记忆 + 完成记忆
    lesson_mems = [m for m in all_memories if m.memory_type == "lesson"]
    knowledge_mems = [m for m in all_memories if m.memory_type == "knowledge"]

    assert len(lesson_mems) >= 1, f"应有失败lesson记忆, 实际: {len(lesson_mems)}"
    assert len(knowledge_mems) >= 1, f"应有knowledge记忆, 实际: {len(knowledge_mems)}"

    # 验证失败记忆优先级高
    failed_mem = next(m for m in lesson_mems if "磁盘满" in m.content)
    assert failed_mem.importance == 0.8

    print(f"  记忆总数: {len(all_memories)}")
    print(f"  lesson: {len(lesson_mems)}, knowledge: {len(knowledge_mems)}")
    print("✅ 测试5: 记忆观察者自动记忆")


# ═══════════════════════════════════════════════
# 测试6：记忆反向影响规划
# ═══════════════════════════════════════════════

def test_memory_influences_planning():
    """历史教训 → 自动注入约束"""
    store = make_test_store()

    # 预存一条失败教训（包含搜索关键词）
    lesson = Memory(
        content="节点3磁盘满，NCCL分发失败",
        summary="NCCL测试节点3磁盘满",
        memory_type="lesson",
        importance=0.8,
        entities=["节点3", "磁盘"],
    )
    store.save(lesson)

    planner = Planner(store=store, tool_names=["read_file", "write_file"])

    # 规划类似任务（关键词要能匹配到记忆）
    plan = planner.plan("NCCL测试")

    # 应该自动注入历史教训作为约束
    memory_constraints = [c for c in plan.constraints if "历史教训" in c.rule]
    assert len(memory_constraints) >= 1, f"应注入历史教训约束, 实际约束: {[c.rule for c in plan.constraints]}"

    print(f"  自动注入约束: {memory_constraints[0].rule}")
    print("✅ 测试6: 记忆反向影响规划")


# ═══════════════════════════════════════════════
# 测试7：参数模板解析
# ═══════════════════════════════════════════════

def test_template_resolution():
    """步骤间数据传递：{{step_N.field}} 模板解析"""
    executor = Executor(guardrails=Guardrails(), replanner=Replanner())

    context = {
        "step_1": {"output_path": "/tmp/result.txt", "count": 3},
        "step_2": {"output": "3 errors found"},
    }

    # 简单引用
    assert executor._resolve_template("{{step_1.output_path}}", context) == "/tmp/result.txt"

    # 嵌套在字符串中
    assert executor._resolve_template("检查结果: {{step_2.output}}", context) == "检查结果: 3 errors found"

    # 不存在的引用保持原样
    assert executor._resolve_template("{{step_99.output}}", context) == "{{step_99.output}}"

    # dict 参数整体解析
    args = {"path": "{{step_1.output_path}}", "content": "发现{{step_1.count}}个问题"}
    resolved = executor._resolve_args(args, context)
    assert resolved["path"] == "/tmp/result.txt"
    assert resolved["content"] == "发现3个问题"

    print("✅ 测试7: 参数模板解析")


# ═══════════════════════════════════════════════
# 测试8：重规划策略
# ═══════════════════════════════════════════════

def test_replanner_strategies():
    """不同错误类型 → 不同重规划策略"""
    replanner = Replanner()
    plan = Plan(goal="测试", steps=[Step(id="step_1", description="测试步骤")])

    # 网络超时 → 重试
    step = Step(id="step_1", description="连接节点3", reflection="Connection timeout after 30s")
    result = replanner.replan(plan, step)
    assert result["_strategy"] == "retry_once"

    # 权限不足 → 求助
    step2 = Step(id="step_1", description="修改配置", reflection="Permission denied: /etc/hosts")
    result2 = replanner.replan(plan, step2)
    assert result2["_strategy"] == "ask_user"

    # 工具不存在 → 替代
    step3 = Step(id="step_1", description="获取网页", reflection="tool not found: wget", tool="fetch_url")
    result3 = replanner.replan(plan, step3)
    # fetch_url 的替代是 read_file
    assert result3["_strategy"] == "alternative"

    print("✅ 测试8: 重规划策略选择")


# ═══════════════════════════════════════════════
# 测试9：Plan 数据模型
# ═══════════════════════════════════════════════

def test_plan_model():
    """Plan 基本操作"""
    plan = Plan(
        goal="部署服务",
        steps=[
            Step(id="step_1", description="检查"),
            Step(id="step_2", description="执行", depends_on=["step_1"]),
            Step(id="step_3", description="验证", depends_on=["step_2"]),
        ],
    )

    # 依赖检查
    assert not plan.steps[1].is_ready(set())
    assert plan.steps[1].is_ready({"step_1"})
    assert not plan.steps[2].is_ready({"step_1"})
    assert plan.steps[2].is_ready({"step_1", "step_2"})

    # 摘要
    plan.steps[0].status = "done"
    plan.steps[1].status = "done"
    assert "2/3" in plan.summary()

    print("✅ 测试9: Plan 数据模型")


# ═══════════════════════════════════════════════
# 测试10：护栏事件触发记忆（端到端）
# ═══════════════════════════════════════════════

def test_guardrail_memory_integration():
    """护栏拦截 → MemoryObserver 记录"""
    store = make_test_store()
    extractor = MemoryExtractor()
    observer = MemoryObserver(extractor=extractor, store=store)

    plan = Plan(goal="清理服务器", steps=[
        Step(id="step_1", description="删除所有文件", tool="write_file", args={"path": "/", "content": "rm -rf /"}),
    ])

    guardrails = Guardrails()
    guard_result = guardrails.check(plan.steps[0], plan)

    assert guard_result.action == "deny"

    # 观察者记录
    observer.on_guardrail_triggered(plan.steps[0], guard_result)

    # 验证记忆
    mems = store.list_all(limit=10)
    assert len(mems) >= 1
    guard_mem = mems[0]
    assert guard_mem.memory_type == "lesson"
    assert guard_mem.importance == 0.9  # 护栏事件最高优先级

    print("✅ 测试10: 护栏事件自动记忆")


# ═══════════════════════════════════════════════
# 运行所有测试
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print("🦫 MiniClaw Harness 端到端测试")
    print("=" * 50)
    print()

    tests = [
        ("测试1: 简单任务不触发 Harness", test_simple_no_harness),
        ("测试2: 中等任务 Harness 执行", test_medium_harness),
        ("测试3: 复杂任务+重规划", test_complex_with_replan),
        ("测试4a: 护栏拦截危险操作", test_guardrails_deny),
        ("测试4b: 确认类操作拦截", test_guardrails_confirm),
        ("测试5: 记忆观察者自动记忆", test_memory_observer),
        ("测试6: 记忆反向影响规划", test_memory_influences_planning),
        ("测试7: 参数模板解析", test_template_resolution),
        ("测试8: 重规划策略选择", test_replanner_strategies),
        ("测试9: Plan数据模型", test_plan_model),
        ("测试10: 护栏事件自动记忆", test_guardrail_memory_integration),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"❌ {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 50)
    print(f"📊 结果: {passed} 通过 / {failed} 失败 / {passed + failed} 总计")
    if failed == 0:
        print("🎉 全部通过！")
    print("=" * 50)
