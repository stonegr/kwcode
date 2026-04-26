"""
ContentFetcher: 页面正文提取，三级降级。
crawl4ai → trafilatura → httpx 简单提取。
每页最多 800 字（SEARCH-RED-4 时间预算内）。
"""

import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 检测可用的正文提取库
_CRAWL4AI_OK = False
_TRAFILATURA_OK = False

try:
    import trafilatura
    _TRAFILATURA_OK = True
except ImportError:
    pass

try:
    import crawl4ai  # noqa
    _CRAWL4AI_OK = True
except ImportError:
    pass


class ContentFetcher:
    """页面正文提取器。crawl4ai → trafilatura → httpx 三级降级。"""

    def __init__(self):
        if _CRAWL4AI_OK:
            logger.info("[fetcher] backend: crawl4ai")
        elif _TRAFILATURA_OK:
            logger.info("[fetcher] backend: trafilatura")
        else:
            logger.warning("[fetcher] backend: httpx fallback (install trafilatura for better results)")

    def fetch(self, url: str, timeout: float = 8.0) -> str:
        """
        提取单个 URL 的正文，返回压缩后文本（≤800字）。
        StackOverflow 走 StackExchange API 绕过 403。
        任何异常返回空字符串。
        """
        try:
            # StackOverflow 直接 fetch 会 403，走免费 API 拿 body
            if "stackoverflow.com/questions/" in url:
                text = self._fetch_stackoverflow(url, timeout)
            elif _CRAWL4AI_OK:
                text = self._fetch_crawl4ai(url, timeout)
            elif _TRAFILATURA_OK:
                text = self._fetch_trafilatura(url, timeout)
            else:
                text = self._fetch_httpx(url, timeout)
            return self._compress(text)
        except Exception as e:
            logger.warning("[fetcher] failed %s: %s", url[:60], e)
            return ""

    def fetch_many(self, urls: list[str], timeout: float = 8.0) -> list[str]:
        """批量提取，串行执行（MVP 不做并发）。"""
        return [self.fetch(url, timeout) for url in urls]

    @staticmethod
    def _fetch_stackoverflow(url: str, timeout: float) -> str:
        """StackOverflow 走 StackExchange API，免费无需 key，直接拿答案 body。"""
        # 从 URL 提取 question id: stackoverflow.com/questions/12345/...
        import re as _re
        match = _re.search(r"stackoverflow\.com/questions/(\d+)", url)
        if not match:
            return ""
        qid = match.group(1)

        try:
            resp = httpx.get(
                "https://api.stackexchange.com/2.3/questions/{}/answers".format(qid),
                params={
                    "site": "stackoverflow",
                    "order": "desc",
                    "sort": "votes",
                    "filter": "withbody",
                    "pagesize": 2,
                },
                timeout=min(timeout, 5.0),
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                return ""

            # 拼接 top 2 答案的 body（HTML），用简单去标签
            parts = []
            for item in items[:2]:
                body = item.get("body", "")
                text = ContentFetcher._html_to_text(body)
                if text:
                    score = item.get("score", 0)
                    parts.append(f"[votes:{score}] {text}")
            return "\n\n".join(parts)
        except Exception as e:
            logger.warning("[fetcher-so] API failed for %s: %s", qid, e)
            return ""

    @staticmethod
    def _fetch_crawl4ai(url: str, timeout: float) -> str:
        """crawl4ai 提取（最佳质量，需要安装浏览器）。"""
        import asyncio
        from crawl4ai import AsyncWebCrawler

        async def _run():
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url)
                return result.markdown if result else ""

        # 在同步上下文中运行异步代码
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已有事件循环（如 Jupyter），降级到 trafilatura
                return ContentFetcher._fetch_trafilatura(url, timeout) if _TRAFILATURA_OK else ""
            return loop.run_until_complete(_run())
        except RuntimeError:
            return asyncio.run(_run())

    @staticmethod
    def _fetch_trafilatura(url: str, timeout: float) -> str:
        """trafilatura 提取（纯 HTTP，质量好）。用 httpx 自己下载以控制超时。"""
        try:
            resp = httpx.get(
                url,
                timeout=min(timeout, 5.0),
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Kaiwu/0.3)"},
            )
            resp.raise_for_status()
            downloaded = resp.text
        except Exception as e:
            logger.warning("[fetcher-traf] download failed %s: %s", url[:50], e)
            return ""
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        return text or ""

    @staticmethod
    def _fetch_httpx(url: str, timeout: float) -> str:
        """httpx 降级：下载 HTML 后简单去标签。"""
        try:
            resp = httpx.get(
                url,
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Kaiwu/0.3)"},
            )
            resp.raise_for_status()
            return ContentFetcher._html_to_text(resp.text)
        except Exception as e:
            logger.warning("[fetcher-httpx] %s: %s", url[:60], e)
            return ""

    @staticmethod
    def _html_to_text(html: str) -> str:
        """简单 HTML → 纯文本（去标签 + 去多余空白）。"""
        # 去 script/style
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # 去所有标签
        text = re.sub(r"<[^>]+>", " ", text)
        # 去 HTML 实体
        text = re.sub(r"&\w+;", " ", text)
        # 压缩空白
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _compress(text: str, max_chars: int = 800) -> str:
        """压缩文本到 max_chars 以内，保留有意义的行。"""
        if not text:
            return ""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars] + "..."
        return result
