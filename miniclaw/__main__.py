"""最简入口 — python -m miniclaw"""

import os
import sys


def _ensure_utf8():
    """确保 stdin/stdout/stderr 使用 UTF-8 编码"""
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    # Windows: 设置控制台代码页为 UTF-8
    if sys.platform == "win32":
        try:
            os.system("chcp 65001 >nul 2>&1")
        except Exception:
            pass
    # 环境变量兜底
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("LANG", "C.UTF-8")


def main():
    _ensure_utf8()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("🦫 MiniClaw v0.5.0")
        print()
        print("用法: python -m miniclaw [配置文件路径]")
        print("默认: python -m miniclaw miniclaw.toml")
        sys.exit(0)

    config_path = sys.argv[1]

    import asyncio
    from miniclaw.chat import run_chat
    asyncio.run(run_chat(config_path))


if __name__ == "__main__":
    main()
