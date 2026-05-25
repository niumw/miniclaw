"""HTTP 访问 Skill — 让 MiniClaw 能访问 HTTP/HTTPS 资源"""

import json
import re
from dataclasses import dataclass

from miniclaw import __version__


@dataclass
class FetchResult:
    """访问结果"""
    url: str
    status: int
    content_type: str
    content: str
    error: str | None = None
    truncated: bool = False


class HttpFetchSkill:
    """HTTP/HTTPS 资源访问"""

    name = "http_fetch"
    description = "访问 HTTP/HTTPS URL 获取内容"

    # 从用户输入中提取 URL 的模式
    URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

    # 最大内容长度（字符数）
    MAX_CONTENT_LENGTH = 5000

    async def fetch(self, url: str, timeout: int = 15) -> FetchResult:
        """
        访问一个 URL 并返回内容。
        支持 text/html, application/json, text/plain 等。
        """
        try:
            import httpx
        except ImportError:
            # 降级到 urllib
            return await self._fetch_urllib(url, timeout)

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers={
                    "User-Agent": f"MiniClaw/{__version__}",
                    "Accept": "text/html,application/json,text/plain,*/*",
                })

                content_type = resp.headers.get("content-type", "")
                content = ""
                truncated = False

                if "application/json" in content_type:
                    try:
                        data = resp.json()
                        content = json.dumps(data, ensure_ascii=False, indent=2)
                    except Exception:
                        content = resp.text
                elif "text/" in content_type or "html" in content_type:
                    content = self._extract_text_from_html(resp.text) if "html" in content_type else resp.text
                else:
                    content = f"[二进制内容, content-type: {content_type}, size: {len(resp.content)} bytes]"

                if len(content) > self.MAX_CONTENT_LENGTH:
                    content = content[:self.MAX_CONTENT_LENGTH]
                    truncated = True

                return FetchResult(
                    url=url,
                    status=resp.status_code,
                    content_type=content_type,
                    content=content,
                    truncated=truncated,
                )

        except Exception as e:
            return FetchResult(url=url, status=0, content_type="", content="", error=str(e))

    async def _fetch_urllib(self, url: str, timeout: int) -> FetchResult:
        """使用 urllib 的降级方案"""
        import urllib.request

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": f"MiniClaw/{__version__}",
                "Accept": "text/html,application/json,text/plain,*/*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("content-type", "")
                raw_bytes = resp.read()

                # 编码检测：优先从 Content-Type 头取，fallback 到 utf-8
                encoding = "utf-8"
                if "charset=" in content_type:
                    encoding = content_type.split("charset=")[-1].split(";")[0].strip().strip('"')
                raw = raw_bytes.decode(encoding, errors="replace")

                if "html" in content_type:
                    raw = self._extract_text_from_html(raw)

                truncated = len(raw) > self.MAX_CONTENT_LENGTH
                content = raw[:self.MAX_CONTENT_LENGTH] if truncated else raw

                return FetchResult(url=url, status=resp.status, content_type=content_type, content=content, truncated=truncated)

        except Exception as e:
            return FetchResult(url=url, status=0, content_type="", content="", error=str(e))

    def _extract_text_from_html(self, html: str) -> str:
        """从 HTML 中提取纯文本（简单实现）"""
        import re
        # 移除 script 和 style
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 标签
        html = re.sub(r'<[^>]+>', ' ', html)
        # 压缩空白
        html = re.sub(r'\s+', ' ', html).strip()
        # 解码常见 HTML 实体
        html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
        return html

    @staticmethod
    def extract_urls(text: str) -> list[str]:
        """从文本中提取 URL"""
        return re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)

    def format_result(self, result: FetchResult) -> str:
        """格式化访问结果，供注入 prompt"""
        if result.error:
            return f"[访问失败] {result.url}\n错误: {result.error}"

        parts = [f"[网页内容] {result.url}"]
        parts.append(f"状态: {result.status} | 类型: {result.content_type}")

        if result.truncated:
            parts.append("(内容已截断)")

        parts.append(result.content)
        return "\n".join(parts)
