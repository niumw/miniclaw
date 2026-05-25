# MiniClaw Changelog

所有 notable 变更都记录在此文件。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

---

## [Unreleased]

### 🎯 本版目标
MiniClaw 从"实验项目"升级为正式项目制运作，建立变更记录和汇报规范

---

## [0.5.0] - 2026-05-23

### 🎯 本版目标
实现 Tool Use 机制，让模型从"只能说话"变成"能用工具"

### ✨ 新增
- `model.py`: 新增 `TOOL_DEFINITIONS`（6个工具定义），`stream_chat` 支持流式 tool_call 解析
- `chat.py`: 实现 `_chat_with_tools_dual()` 双轨 tool call 循环（Function Calling + 文本解析），最大5轮
- `router.py`: 新增 `_recommend_tools()` 根据用户输入推荐可用工具
- `miniclaw.toml`: 更新 system prompt，告知模型有工具能力
- 6个工具：read_file / write_file / list_dir / search_memory / save_memory / fetch_url
- `skills/file_io.py`: 文件读写 Skill
- `skills/http_fetch.py`: URL 抓取 Skill

### 🔧 修复
- #0 模型无法主动调用工具（记忆存储+文件读取不可用）
- #4 巩固器不合并 data 层记忆 → `_merge_similar()` 条件扩展
- #5 反射规则关键词误匹配（"hi"匹配"this"）→ 中文包含匹配，英文词边界匹配
- #7 记忆注入位置错误 → 合并到开头 system prompt 末尾

### 📐 架构
- 引入双轨 Tool Use：轨道1（Function Calling）+ 轨道2（文本解析），自动切换
- 工具执行器映射表，统一管理工具调用

---

## [0.4.0] - 2026-05-22

### 🎯 本版目标
完善记忆系统，三层路由可用

### ✨ 新增
- `memory/router.py`: 三层路由实现（反射→直觉→深思）
- `memory/relations.py`: 自动关联关系（共同实体/标签→relates_to/similar）
- `memory/consolidator.py`: 后台巩固（反思+合并+衰减+规则提升）

### 🔧 修复
- 反射层规则匹配基本可用
- 巩固器可在退出时触发

---

## [0.3.0] - 2026-05-21

### 🎯 本版目标
记忆系统核心完成——存、取、衰减

### ✨ 新增
- `memory/store.py`: SQLite 持久化，DIKW 分层存储
- `memory/extractor.py`: 5条规则的记忆提取
- `memory/retriever.py`: 多路召回 + 联想扩展
- `memory/decay.py`: 衰减计算 + 软硬遗忘

---

## [0.2.0] - 2026-05-20

### 🎯 本版目标
基本对话循环可用

### ✨ 新增
- `chat.py`: 交互式对话循环
- `model.py`: OpenAI 兼容 API 流式调用
- `config.py`: TOML 配置加载
- `/memories` 和 `/consolidate` 命令

---

## [0.1.0] - 2026-05-19

### 🎯 本版目标
项目初始化，最小可运行版本

### ✨ 新增
- `__main__.py`: 入口
- 基本的项目结构
