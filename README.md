# MiniClaw v0.4.0

轻量 AI 助手，带记忆系统、DIKW 分层、三层路由。

## 快速开始

```bash
# 安装依赖
pip install openai rich

# 编辑配置（填入你的 API key 和模型地址）
vim miniclaw.toml

# 运行
python -m miniclaw miniclaw.toml
```

## 配置说明

编辑 `miniclaw.toml`：

```toml
[model]
primary = "openai/你的模型名"

[model.providers.openai]
api_key = "你的API密钥"
base_url = "你的API地址"

[system]
prompt = """你是 MiniClaw，一个轻量但可靠的 AI 助手。
你的特点：
- 用中文交流，简洁高效
- 遇到不确定的事情先问再做
- 能自己想明白的就自己想，不反复问用户"""

[memory]
db_path = "data/miniclaw.db"
max_retrieve = 3
token_budget = 1500
```

## 交互命令

| 命令 | 功能 |
|------|------|
| `/memories` | 查看所有记忆 |
| `/consolidate` | 手动触发巩固 |
| `Ctrl+C` | 退出（自动执行巩固） |

## 架构

```
三层路由：
  ⚡ 反射层 — 规则匹配，零模型调用
  💭 直觉层 — 记忆直答+轻量验证
  🧠 深思层 — 完整模型推理

记忆系统：
  存储: SQLite (DIKW 四层)
  提取: 4条规则 (明确标记/实体/纠错/偏好)
  检索: 实体→标签→关键词多路召回+联想扩展
  巩固: 反思+合并+衰减+规则提升
  遗忘: 软遗忘(抑制) → 硬遗忘(归档)
```

## 依赖

- Python 3.11+
- openai >= 1.30
- rich >= 13.0

## 文件结构

```
miniclaw/
├── miniclaw/
│   ├── __init__.py
│   ├── __main__.py          # 入口
│   ├── chat.py              # 对话循环 + 路由 + 记忆提取
│   ├── config.py            # TOML 配置加载
│   ├── model.py             # OpenAI 兼容 API 流式调用
│   └── memory/
│       ├── store.py         # SQLite 持久化 (DIKW + 关联 + 规则)
│       ├── extractor.py     # 从对话中提取记忆
│       ├── retriever.py     # 多路召回 + 联想扩展
│       ├── consolidator.py  # 后台巩固
│       ├── decay.py         # 衰减计算
│       ├── relations.py     # 关联关系
│       └── router.py        # 三层路由
├── miniclaw.toml            # 配置文件
├── requirements.txt
├── pyproject.toml
└── docs/
    └── memory-system-design.md  # 完整设计文档
```
