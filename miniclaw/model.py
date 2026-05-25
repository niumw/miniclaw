"""模型调用 — 流式对话 + Function Calling + 文本解析双轨 Tool Use"""

import json
import re
from typing import AsyncGenerator
from openai import AsyncOpenAI


# ── Tool 定义 ──

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取本地文件内容。支持文本文件（.txt/.md/.py/.json/.yaml/.toml/.csv 等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，可以是绝对路径或相对路径",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入内容到本地文件。会自动创建不存在的目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的内容",
                    },
                    "append": {
                        "type": "boolean",
                        "description": "是否追加模式（默认覆盖）",
                        "default": False,
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出目录内容，显示文件和子目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录路径，默认为当前目录",
                        "default": ".",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "搜索记忆库中与查询相关的记忆。用于回忆之前学到的信息、用户偏好、经验教训等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或描述",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "主动保存一条重要信息到记忆库。用于记住用户偏好、重要事实、经验教训等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要记住的完整内容",
                    },
                    "summary": {
                        "type": "string",
                        "description": "一句话摘要（不超过50字）",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["knowledge", "preference", "lesson", "event", "skill"],
                        "description": "记忆类型",
                        "default": "knowledge",
                    },
                    "importance": {
                        "type": "number",
                        "description": "重要性 0-1，0.9=极其重要，0.5=一般",
                        "default": 0.7,
                    },
                },
                "required": ["content", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "访问URL并获取网页内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要访问的URL",
                    },
                },
                "required": ["url"],
            },
        },
    },
]


# ── 文本解析模式：从模型回复中提取工具调用 ──
# 当模型不支持 function calling 时，从文本中解析结构化的工具调用

# 匹配 ```tool_call 或 ```json 块
TOOL_CALL_BLOCK_RE = re.compile(
    r'```(?:tool_call|json)\s*\n(.*?)```',
    re.DOTALL,
)

# 工具名白名单
TOOL_NAMES = {"read_file", "write_file", "list_dir", "search_memory", "save_memory", "fetch_url"}


def parse_tool_calls_from_text(text: str) -> list[dict]:
    """
    从模型文本回复中解析出工具调用。
    支持格式：
    1. ```tool_call\n{"name": "read_file", "arguments": {"path": "..."}}\n```
    2. ```json\n{"name": "read_file", "arguments": {"path": "..."}}\n```
    """
    calls = []
    for match in TOOL_CALL_BLOCK_RE.finditer(text):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        # 格式1: {"name": "...", "arguments": {...}}
        if isinstance(data, dict) and "name" in data and data["name"] in TOOL_NAMES:
            calls.append({
                "id": f"parsed_{len(calls)}",
                "type": "function",
                "function": {
                    "name": data["name"],
                    "arguments": json.dumps(data.get("arguments", {}), ensure_ascii=False),
                },
            })

        # 格式2: 数组 [{"name": ..., "arguments": ...}, ...]
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "name" in item and item["name"] in TOOL_NAMES:
                    calls.append({
                        "id": f"parsed_{len(calls)}",
                        "type": "function",
                        "function": {
                            "name": item["name"],
                            "arguments": json.dumps(item.get("arguments", {}), ensure_ascii=False),
                        },
                    })

    return calls


def strip_tool_call_blocks(text: str) -> str:
    """移除文本中的工具调用块，只保留普通文本"""
    return TOOL_CALL_BLOCK_RE.sub("", text).strip()


# ── 构建工具描述 prompt（给不支持 function calling 的模型用）──

def build_tools_prompt() -> str:
    """生成工具描述文本，注入到 system prompt 中"""
    lines = ["\n## 可用工具\n", "你可以通过输出 JSON 代码块来调用工具。格式如下：", "```tool_call", '{"name": "工具名", "arguments": {参数}}', "```\n", "可用工具列表：\n"]
    for t in TOOL_DEFINITIONS:
        f = t["function"]
        params_desc = []
        props = f["parameters"].get("properties", {})
        required = f["parameters"].get("required", [])
        for pname, pinfo in props.items():
            req_mark = "（必填）" if pname in required else "（可选）"
            params_desc.append(f"    - {pname}: {pinfo.get('description', '')}{req_mark}")
        lines.append(f"- **{f['name']}**: {f['description']}")
        if params_desc:
            lines.append("  参数:")
            lines.extend(params_desc)
        lines.append("")

    lines.append("注意：每次只调用一个工具。调用后我会把结果告诉你，然后你再决定下一步。")
    return "\n".join(lines)


# ── 模型调用 ──

async def stream_chat(
    messages: list[dict],
    model_id: str,
    api_key: str,
    base_url: str | None = None,
    tools: list[dict] | None = None,
) -> AsyncGenerator[str | dict, None]:
    """
    调用模型，流式 yield 文本片段或 tool_call 结果。
    
    - 文本片段: str
    - tool_call: {"type": "tool_call", "tool_call": {...}}
    """
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    kwargs = {
        "model": model_id,
        "messages": messages,
        "stream": True,
    }

    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    stream = await client.chat.completions.create(**kwargs)

    # 流式收集 tool_calls（它们可能分多个 chunk 到达）
    tool_calls_buffer: dict[int, dict] = {}

    async for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        # 普通文本
        if delta.content:
            yield delta.content

        # Tool call 片段
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls_buffer:
                    tool_calls_buffer[idx] = {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                buf = tool_calls_buffer[idx]
                if tc_delta.id:
                    buf["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        buf["function"]["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        buf["function"]["arguments"] += tc_delta.function.arguments

    # 流结束后，如果有 tool_calls，逐个 yield
    if tool_calls_buffer:
        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]
            # 验证 arguments 是合法 JSON
            try:
                json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = tc["function"]["arguments"]
                if not args:
                    tc["function"]["arguments"] = "{}"
                else:
                    for _ in range(3):
                        try:
                            json.loads(args + "}")
                            args += "}"
                            break
                        except json.JSONDecodeError:
                            break
                    tc["function"]["arguments"] = args

            yield {"type": "tool_call", "tool_call": tc}


async def call_model_final(
    messages: list[dict],
    model_id: str,
    api_key: str,
    base_url: str | None = None,
) -> str:
    """非流式调用模型，返回完整文本回复"""
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    response = await client.chat.completions.create(
        model=model_id,
        messages=messages,
    )

    return response.choices[0].message.content or ""
