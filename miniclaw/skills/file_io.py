"""文件系统 Skill — 让 MiniClaw 能读写本地文件和目录"""

import os
import json
from dataclasses import dataclass, field


@dataclass
class FileResult:
    """文件操作结果"""
    success: bool
    path: str
    content: str = ""
    error: str | None = None
    size: int = 0
    is_dir: bool = False
    encoding: str = "utf-8"


class FileIOSkill:
    """本地文件系统读写"""

    name = "file_io"
    description = "读写本地文件、列出目录、查询文件信息"

    # 安全限制
    MAX_READ_SIZE = 100_000  # 最大读取字节数
    ALLOWED_EXTENSIONS = {
        # 文本
        ".txt", ".md", ".csv", ".tsv", ".log", ".ini", ".cfg", ".conf", ".toml",
        ".yaml", ".yml", ".json", ".jsonl", ".xml", ".html", ".htm", ".css",
        # 代码
        ".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
        ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
        ".sql", ".r", ".rb", ".php", ".pl", ".lua", ".vim",
        # 配置
        ".env", ".gitignore", ".dockerignore", ".editorconfig",
        # 数据
        ".db", ".sqlite", ".sqlite3",
    }
    DENIED_PATHS = {
        # 敏感路径
        "/etc/shadow", "/etc/passwd", "/etc/ssh",
        "/root/.ssh", "/home/*/.ssh",
    }

    def read_file(self, path: str, encoding: str = "utf-8", max_lines: int = 500) -> FileResult:
        """读取文件内容"""
        try:
            path = os.path.expanduser(path)
            path = os.path.abspath(path)

            if not os.path.exists(path):
                return FileResult(success=False, path=path, error="文件不存在")

            if os.path.isdir(path):
                return FileResult(success=False, path=path, error="是目录，不是文件。请用 list_dir", is_dir=True)

            # 安全检查
            safe, reason = self._check_safety(path)
            if not safe:
                return FileResult(success=False, path=path, error=reason)

            # 文件大小检查
            size = os.path.getsize(path)
            if size > self.MAX_READ_SIZE:
                return FileResult(
                    success=False, path=path,
                    error=f"文件太大 ({size} 字节，限制 {self.MAX_READ_SIZE})",
                    size=size,
                )

            # 读取
            with open(path, "r", encoding=encoding, errors="replace") as f:
                lines = f.readlines()

            if len(lines) > max_lines:
                content = "".join(lines[:max_lines])
                content += f"\n... (共 {len(lines)} 行，仅显示前 {max_lines} 行)"
            else:
                content = "".join(lines)

            return FileResult(success=True, path=path, content=content, size=size)

        except PermissionError:
            return FileResult(success=False, path=path, error="权限不足")
        except Exception as e:
            return FileResult(success=False, path=path, error=str(e))

    def write_file(self, path: str, content: str, encoding: str = "utf-8", append: bool = False) -> FileResult:
        """写入文件"""
        try:
            path = os.path.expanduser(path)
            path = os.path.abspath(path)

            # 安全检查
            safe, reason = self._check_safety(path, write=True)
            if not safe:
                return FileResult(success=False, path=path, error=reason)

            # 创建目录
            os.makedirs(os.path.dirname(path), exist_ok=True)

            mode = "a" if append else "w"
            with open(path, mode, encoding=encoding) as f:
                f.write(content)

            size = os.path.getsize(path)
            action = "追加" if append else "写入"
            return FileResult(success=True, path=path, content=f"{action}成功", size=size)

        except PermissionError:
            return FileResult(success=False, path=path, error="权限不足")
        except Exception as e:
            return FileResult(success=False, path=path, error=str(e))

    def list_dir(self, path: str = ".", pattern: str = "*", max_entries: int = 100) -> FileResult:
        """列出目录内容"""
        import glob as glob_mod

        try:
            path = os.path.expanduser(path)
            path = os.path.abspath(path)

            if not os.path.isdir(path):
                return FileResult(success=False, path=path, error="不是目录")

            # 列出文件
            entries = []
            for entry in sorted(os.listdir(path)):
                full = os.path.join(path, entry)
                if os.path.isdir(full):
                    entries.append(f"📁 {entry}/")
                else:
                    size = os.path.getsize(full)
                    entries.append(f"📄 {entry} ({self._format_size(size)})")

                if len(entries) >= max_entries:
                    entries.append(f"... (超过 {max_entries} 个条目，已截断)")
                    break

            content = f"目录: {path}\n共 {len(os.listdir(path))} 项\n\n" + "\n".join(entries)
            return FileResult(success=True, path=path, content=content, is_dir=True)

        except PermissionError:
            return FileResult(success=False, path=path, error="权限不足")
        except Exception as e:
            return FileResult(success=False, path=path, error=str(e))

    def file_info(self, path: str) -> FileResult:
        """获取文件/目录信息"""
        try:
            path = os.path.expanduser(path)
            path = os.path.abspath(path)

            if not os.path.exists(path):
                return FileResult(success=False, path=path, error="不存在")

            stat = os.stat(path)
            is_dir = os.path.isdir(path)
            import time
            content = "\n".join([
                f"路径: {path}",
                f"类型: {'目录' if is_dir else '文件'}",
                f"大小: {self._format_size(stat.st_size)}",
                f"修改时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))}",
                f"创建时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_ctime))}",
            ])
            return FileResult(success=True, path=path, content=content, size=stat.st_size, is_dir=is_dir)

        except Exception as e:
            return FileResult(success=False, path=path, error=str(e))

    def _check_safety(self, path: str, write: bool = False) -> tuple[bool, str]:
        """安全检查"""
        # 路径遍历检查
        real = os.path.realpath(path)

        # 拒绝敏感路径
        for denied in self.DENIED_PATHS:
            if real.startswith(denied) or path.startswith(denied):
                return False, f"禁止访问敏感路径: {denied}"

        # 写入时额外检查
        if write:
            ext = os.path.splitext(path)[1].lower()
            # 允许无扩展名（如 Makefile）
            if ext and ext not in self.ALLOWED_EXTENSIONS:
                return False, f"不允许写入 .{ext} 文件"

        return True, ""

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"
