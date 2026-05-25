"""交互式对话 — 三层路由 + 双轨 Tool Use + 记忆 + 巩固

双轨 Tool Use:
1. Function Calling（原生）：如果模型支持 tools 参数，走标准 tool_call 流程
2. 文本解析（兼容）：如果模型不支持 function calling 或没返回 tool_call，
   从模型文本回复中解析 ```tool_call 块，手动执行
"""

import asyncio
import json
import os
import sys

from rich.console import Console

# 确保 stdout/stderr 编码为 UTF-8
for _sn in ("stdout", "stderr"):
    _stream = getattr(sys, _sn)
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from miniclaw.config import load_config
from miniclaw.model import (
    stream_chat,
    TOOL_DEFINITIONS,
    TOOL_NAMES,
    parse_tool_calls_from_text,
    strip_tool_call_blocks,
    build_tools_prompt,
)
from miniclaw.memory.store import MemoryStore, Memory
from miniclaw.memory.extractor import MemoryExtractor
from miniclaw.memory.retriever import MemoryRetriever
from miniclaw.memory.consolidator import Consolidator
from miniclaw.memory.relations import auto_link_related
from miniclaw.memory.router import Router
from miniclaw.skills.http_fetch import HttpFetchSkill
from miniclaw.skills.file_io import FileIOSkill

console = Console()

# 最大 tool call 循环次数（防止无限循环）
MAX_TOOL_ROUNDS = 5


async def run_chat(config_path: str):
    """主对话循环"""
    config = load_config(config_path)
    provider_id, model_id, provider_cfg = config.resolve()

    env_prefix = provider_id.upper()
    api_key = provider_cfg.get_api_key() or os.environ.get(f"{env_prefix}_API_KEY", "")
    base_url = provider_cfg.base_url or os.environ.get(f"{env_prefix}_BASE_URL", "")

    if not api_key:
        console.print(f"[red]❌ 未配置 API key。请编辑 {config_path} 或设置环境变量 {env_prefix}_API_KEY[/]")
        return

    # 初始化系统
    store = MemoryStore(db_path=config.memory.db_path)
    extractor = MemoryExtractor()
    retriever = MemoryRetriever(store=store, max_results=config.memory.max_retrieve, token_budget=config.memory.token_budget)
    consolidator = Consolidator(store=store)
    router = Router(store=store, retriever=retriever)
    http_skill = HttpFetchSkill()
    file_skill = FileIOSkill()

    # Tool 执行器映射
    tool_executors = {
        "read_file": lambda args: _exec_read_file(file_skill, args),
        "write_file": lambda args: _exec_write_file(file_skill, args),
        "list_dir": lambda args: _exec_list_dir(file_skill, args),
        "search_memory": lambda args: _exec_search_memory(store, retriever, args),
        "save_memory": lambda args: _exec_save_memory(store, args),
        "fetch_url": lambda args: _exec_fetch_url(http_skill, args),
    }

    # 启动巩固
    consolidation = consolidator.consolidate()
    if any(v > 0 for v in consolidation.values()):
        console.print(f"[dim]🔄 启动巩固: {consolidation}[/]")

    # Banner
    console.print()
    console.print(f"[bold yellow]🦫 MiniClaw v0.5.0[/]")
    console.print(f"[dim]Model: {provider_id}/{model_id} | Base: {base_url or 'default'}[/]")
    if config.system.prompt:
        console.print(f"[dim]System: ✅[/]")
    console.print(f"[dim]Memory: ✅ {store.count()} 条 | Tools: 📁file 🌐fetch 💾memory[/]")
    console.print(f"[dim]输入消息开始对话，/memories /consolidate，Ctrl+C 退出[/]")
    console.print()

    messages: list[dict] = []
    if config.system.prompt:
        # 注入工具描述到 system prompt（兼容不支持 function calling 的模型）
        tools_prompt = build_tools_prompt()
        messages.append({"role": "system", "content": config.system.prompt + tools_prompt})

    while True:
        try:
            user_input = console.input("[bold green]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]🔄 巩固中...[/]")
            result = consolidator.consolidate()
            console.print(f"[dim]巩固结果: {result}[/]")
            console.print("[dim]Bye! 🦫[/]")
            break

        if not user_input:
            continue

        # ── 特殊命令 ──
        if user_input == "/memories":
            _print_memories(store)
            continue

        if user_input == "/consolidate":
            result = consolidator.consolidate()
            console.print(f"[bold]🔄 巩固结果:[/] {result}\n")
            continue

        # ── 路由 ──
        route_result = router.route(user_input)
        layer = route_result["layer"]
        rule = route_result["rule"]
        route_memories = route_result["memories"]
        recommended_tools = route_result.get("tools", [])

        # 层1：反射
        if layer == "reflex":
            console.print(f"[dim]⚡ 反射层: {route_result['reason']}[/]")
            console.print(rule["response"])
            store._connect().execute("UPDATE rules SET trigger_count = trigger_count + 1, success_count = success_count + 1 WHERE id = ?", (rule["id"],))
            store._connect().commit()
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": rule["response"]})
            if rule.get("source_memory_id"):
                mem = store.get(rule["source_memory_id"])
                if mem:
                    store.update(mem.id, apply_count=mem.apply_count + 1)
            continue

        # 层2/3：调模型（带双轨 tool use）
        memory_text = retriever.format_for_prompt(route_memories)

        send_messages = list(messages)

        # 记忆注入到 system prompt
        system_addons = []
        if memory_text:
            system_addons.append(memory_text)
        if system_addons:
            if send_messages and send_messages[0]["role"] == "system":
                send_messages[0] = {
                    "role": "system",
                    "content": send_messages[0]["content"] + "\n\n" + "\n\n".join(system_addons),
                }
            else:
                send_messages.insert(0, {"role": "system", "content": "\n\n".join(system_addons)})

        send_messages.append({"role": "user", "content": user_input})

        try:
            if layer == "intuition":
                console.print(f"[dim]💭 直觉层: {route_result['reason']}[/]")
            else:
                console.print(f"[dim]🧠 深思层: {route_result['reason']}[/]")
                if recommended_tools:
                    console.print(f"[dim]🔧 可用工具: {', '.join(recommended_tools)}[/]")

            console.print()

            # ── 双轨 Tool Call 循环 ──
            full_reply = await _chat_with_tools_dual(
                send_messages=send_messages,
                model_id=model_id,
                api_key=api_key,
                base_url=base_url,
                tools=TOOL_DEFINITIONS,  # 始终传全部 tools
                tool_executors=tool_executors,
                max_rounds=MAX_TOOL_ROUNDS,
            )

            console.print("\n")

            if full_reply:
                messages.append({"role": "user", "content": user_input})
                messages.append({"role": "assistant", "content": full_reply})

                for mem in route_memories:
                    store.update(mem.id, apply_count=mem.apply_count + 1)

                new_memories = extractor.extract(user_input, full_reply)
                recent_memories = store.list_all(limit=20)

                for mem in new_memories:
                    similar = store.search(query=mem.summary, limit=3)
                    is_dup = False
                    for existing in similar:
                        if existing.summary == mem.summary or _memories_similar(existing, mem):
                            if mem.importance > existing.importance:
                                store.supersede(existing.id, mem.id)
                                store.save(mem)
                                auto_link_related(store, mem, recent_memories)
                                console.print(f"[dim]💾 记忆更新: {mem.summary[:40]}[/]")
                            is_dup = True
                            break
                    if not is_dup:
                        store.save(mem)
                        auto_link_related(store, mem, recent_memories)
                        console.print(f"[dim]💾 记忆保存: {mem.summary[:40]}[/]")

        except Exception as e:
            console.print(f"\n[red]❌ 调用失败: {e}[/]")


async def _chat_with_tools_dual(
    send_messages: list[dict],
    model_id: str,
    api_key: str,
    base_url: str | None,
    tools: list[dict],
    tool_executors: dict,
    max_rounds: int = 5,
) -> str:
    """
    双轨工具调用循环：
    
    轨道1 (Function Calling): 模型原生返回 tool_call → 执行 → 回传
    轨道2 (文本解析): 模型不支持 FC，在文本中输出 ```tool_call 块 → 解析 → 执行 → 回传
    
    两轨自动切换，对用户透明。
    """
    current_messages = list(send_messages)
    full_reply = ""

    for round_num in range(max_rounds):
        text_chunks = []
        native_tool_calls = []
        # 用于轨道2的缓冲：等流结束后再判断是否有 tool_call 块
        track2_text_buffer = ""
        using_fallback = False

        # 尝试用 function calling 调用
        try:
            async for chunk in stream_chat(
                messages=current_messages,
                model_id=model_id,
                api_key=api_key,
                base_url=base_url,
                tools=tools,  # 始终传 tools
            ):
                if isinstance(chunk, str):
                    text_chunks.append(chunk)
                    # 轨道1：实时打印文本
                    if not using_fallback:
                        console.print(chunk, end="", highlight=False)
                elif isinstance(chunk, dict) and chunk.get("type") == "tool_call":
                    native_tool_calls.append(chunk["tool_call"])
        except Exception as e:
            # 模型可能不支持 tools 参数，退回无 tools 调用
            error_msg = str(e).lower()
            if "tool" in error_msg or "function" in error_msg or "unsupported" in error_msg or "invalid" in error_msg:
                console.print(f"[dim]⚠️ 模型不支持 function calling，切换到文本解析模式[/]")
                text_chunks = []
                native_tool_calls = []
                using_fallback = True
                async for chunk in stream_chat(
                    messages=current_messages,
                    model_id=model_id,
                    api_key=api_key,
                    base_url=base_url,
                ):
                    if isinstance(chunk, str):
                        text_chunks.append(chunk)
                        # 轨道2：先缓冲，流结束后再判断有没有 tool_call 块
                        track2_text_buffer += chunk
            else:
                raise

        full_text = "".join(text_chunks)

        # ── 轨道1: 原生 Function Calling ──
        if native_tool_calls:
            # 文本已经实时打印过了
            console.print()  # 换行

            # 执行 tool calls
            tool_results = await _execute_tool_calls(native_tool_calls, tool_executors, current_messages)
            
            full_reply += full_text
            continue

        # ── 轨道2: 文本解析 ──
        parsed_tool_calls = parse_tool_calls_from_text(full_text)

        if parsed_tool_calls:
            # 移除工具调用块，只保留普通文本
            display_text = strip_tool_call_blocks(full_text)
            if display_text:
                console.print(display_text, end="", highlight=False)

            # 执行解析出的 tool calls
            tool_results = await _execute_tool_calls(parsed_tool_calls, tool_executors, current_messages)
            
            full_reply += display_text
            continue

        # 没有工具调用，对话完成
        if full_text:
            # 轨道2模式下文本还没打印，现在补打
            if using_fallback:
                console.print(full_text, end="", highlight=False)
            full_reply += full_text
            break

        # 既没有文本也没有 tool_call，退出
        break

    return full_reply


async def _execute_tool_calls(
    tool_calls: list[dict],
    tool_executors: dict,
    current_messages: list[dict],
) -> list[str]:
    """执行一组 tool calls，把结果加入消息历史，返回结果列表"""
    # 把 assistant 的 tool_call 消息加入历史
    current_messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": tool_calls,
    })

    results = []
    for tc in tool_calls:
        func_name = tc["function"]["name"]
        func_args_str = tc["function"]["arguments"]
        call_id = tc.get("id", func_name)

        try:
            func_args = json.loads(func_args_str)
        except json.JSONDecodeError:
            func_args = {}

        # 执行 tool
        console.print(f"\n[dim]🔧 调用: {func_name}({', '.join(f'{k}={v!r}' for k, v in func_args.items())})[/]")

        executor = tool_executors.get(func_name)
        if executor:
            try:
                result = executor(func_args)
                result_str = str(result)
                if len(result_str) > 8000:
                    result_str = result_str[:8000] + "\n...(内容过长，已截断)"
                console.print(f"[dim]   ✅ 结果: {result_str[:100]}{'...' if len(result_str) > 100 else ''}[/]")
            except Exception as e:
                result_str = f"工具执行失败: {e}"
                console.print(f"[dim]   ❌ 失败: {e}[/]")
        else:
            result_str = f"未知工具: {func_name}"
            console.print(f"[dim]   ❌ 未知工具[/]")

        results.append(result_str)

        # 把 tool 结果加入消息历史
        current_messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": result_str,
        })

    return results


# ── Tool 执行器实现 ──

def _exec_read_file(file_skill: FileIOSkill, args: dict) -> str:
    result = file_skill.read_file(args.get("path", ""))
    if result.success:
        return result.content
    return f"读取失败: {result.error}"


def _exec_write_file(file_skill: FileIOSkill, args: dict) -> str:
    result = file_skill.write_file(
        path=args.get("path", ""),
        content=args.get("content", ""),
        append=args.get("append", False),
    )
    if result.success:
        return result.content
    return f"写入失败: {result.error}"


def _exec_list_dir(file_skill: FileIOSkill, args: dict) -> str:
    result = file_skill.list_dir(args.get("path", "."))
    if result.success:
        return result.content
    return f"列目录失败: {result.error}"


def _exec_search_memory(store: MemoryStore, retriever: MemoryRetriever, args: dict) -> str:
    query = args.get("query", "")
    if not query:
        return "请提供搜索关键词"

    memories = retriever.retrieve(query)
    if not memories:
        return "未找到相关记忆"

    lines = []
    for m in memories:
        status = "✅" if m.status == "verified" else "🟡"
        lines.append(f"{status} [{m.memory_type}/{m.dikw_level}] {m.summary}")
        if m.entities:
            lines.append(f"   实体: {', '.join(m.entities[:5])}")
    return "\n".join(lines)


def _exec_save_memory(store: MemoryStore, args: dict) -> str:
    content = args.get("content", "")
    summary = args.get("summary", "")
    memory_type = args.get("memory_type", "knowledge")
    importance = args.get("importance", 0.7)

    if not content:
        return "内容不能为空"

    if not summary:
        summary = content[:50]

    from miniclaw.memory.extractor import MemoryExtractor
    extractor = MemoryExtractor()
    entities = extractor._extract_entities(content, "")
    tags = extractor._infer_tags(content)

    mem = Memory(
        content=content,
        summary=summary,
        memory_type=memory_type,
        importance=importance,
        entities=entities,
        tags=tags,
    )

    # 去重检查
    similar = store.search(query=summary, limit=3)
    for existing in similar:
        if existing.summary == summary:
            return f"已存在相同记忆: {summary[:40]}"

    store.save(mem)
    recent = store.list_all(limit=20)
    auto_link_related(store, mem, recent)

    return f"已保存: {summary[:40]}"


async def _exec_fetch_url_sync(http_skill: HttpFetchSkill, args: dict) -> str:
    url = args.get("url", "")
    if not url:
        return "请提供URL"
    result = await http_skill.fetch(url)
    if result.error:
        return f"访问失败: {result.error}"
    content = result.content
    if len(content) > 8000:
        content = content[:8000] + "\n...(内容过长，已截断)"
    return content


def _exec_fetch_url(http_skill: HttpFetchSkill, args: dict) -> str:
    """同步包装的 fetch_url"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    _exec_fetch_url_sync(http_skill, args),
                )
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(_exec_fetch_url_sync(http_skill, args))
    except RuntimeError:
        return asyncio.run(_exec_fetch_url_sync(http_skill, args))


def _print_memories(store: MemoryStore):
    mems = store.list_all(limit=20)
    if not mems:
        console.print("[dim]暂无记忆[/]\n")
    else:
        console.print(f"\n[bold]📋 记忆列表 ({store.count()} 条)[/]")
        for m in mems:
            status_icon = {"unverified": "🟡", "verified": "✅", "needs_review": "🔴"}.get(m.status, "❓")
            dikw_icon = {"data": "1️⃣", "information": "2️⃣", "knowledge": "3️⃣", "wisdom": "4️⃣"}.get(m.dikw_level, "❓")
            console.print(f"  {dikw_icon} {status_icon} [{m.memory_type}] imp={m.importance:.1f} | {m.summary[:50]}")
            if m.entities:
                console.print(f"      entities: {m.entities}")
    console.print()


def _memories_similar(a, b) -> bool:
    """判断两条记忆是否相似（去重用）"""
    if a.summary == b.summary:
        return True
    if a.entities and b.entities:
        common = set(a.entities) & set(b.entities)
        if common:
            words_a = set(a.summary)
            words_b = set(b.summary)
            overlap = len(words_a & words_b) / max(len(words_a | words_b), 1)
            if overlap > 0.6:
                return True
    return False
