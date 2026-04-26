"""
SearchAugmentor expert: triggered on failure (2x) or hard tasks.
Searches web for solutions, compresses results, injects into context.
RED-5: Part of retry budget (max 3 total).
"""

import json
import logging
from typing import Optional

from kaiwu.core.context import TaskContext
from kaiwu.llm.llama_backend import LLMBackend

logger = logging.getLogger(__name__)

QUERY_GEN_PROMPT = """你是搜索查询生成器。根据任务描述和错误信息，生成2-3个精准的英文技术搜索query。

任务描述：{task_description}
错误信息：{error_detail}

返回JSON格式：
{{"queries": ["query1", "query2"]}}

要求：
1. 用英文搜索（技术内容英文结果更好）
2. 包含具体技术栈名称
3. 只返回JSON"""

SUMMARIZE_PROMPT = """你是技术摘要专家。从搜索结果中提取与当前任务最相关的3-5个关键技术要点。

当前任务：{task_description}
当前错误：{error_detail}

搜索结果：
{search_results}

返回简洁的技术要点列表（每条不超过50字），格式：
1. 要点一
2. 要点二
3. 要点三

只返回要点，不要其他内容。"""


class SearchAugmentorExpert:
    """Search-augmented rescue. Generates queries, fetches results, compresses into context."""

    def __init__(self, llm: LLMBackend, search_fn=None):
        self.llm = llm
        # search_fn: callable(query: str) -> list[dict] with keys: title, snippet, url
        # Default: DuckDuckGo (FLEX-3: replaceable)
        self._search_fn = search_fn or self._default_search

    def search(self, ctx: TaskContext) -> str:
        """
        Full search pipeline:
        1. Generate queries from task + error
        2. Execute searches
        3. Summarize results
        Returns compressed search context string.
        """
        error_detail = ""
        if ctx.verifier_output:
            error_detail = ctx.verifier_output.get("error_detail", "")

        # Step 1: Generate search queries
        queries = self._generate_queries(ctx.user_input, error_detail)
        if not queries:
            queries = [ctx.user_input[:100]]  # Fallback: use raw input

        # Step 2: Execute searches
        all_results = []
        for q in queries[:3]:  # Cap at 3 queries
            results = self._search_fn(q)
            all_results.extend(results)

        if not all_results:
            logger.warning("SearchAugmentor: no results found")
            return ""

        # Step 3: Summarize (compress into key facts)
        raw_text = self._format_results(all_results[:10])  # Cap at 10 results
        summary = self._summarize(ctx.user_input, error_detail, raw_text)

        logger.info("SearchAugmentor: found %d results, summarized", len(all_results))
        return summary

    def _generate_queries(self, task_desc: str, error_detail: str) -> list[str]:
        """Use LLM to generate precise search queries."""
        prompt = QUERY_GEN_PROMPT.format(
            task_description=task_desc,
            error_detail=error_detail or "(无错误信息)",
        )
        raw = self.llm.generate(prompt=prompt, max_tokens=200, temperature=0.0)

        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                data = json.loads(raw[start:end + 1])
                return data.get("queries", [])
        except (json.JSONDecodeError, KeyError):
            pass

        logger.warning("Query generation parse failed: %s", raw[:200])
        return []

    def _summarize(self, task_desc: str, error_detail: str, raw_results: str) -> str:
        """Compress search results into key technical facts."""
        prompt = SUMMARIZE_PROMPT.format(
            task_description=task_desc,
            error_detail=error_detail or "(无错误信息)",
            search_results=raw_results[:3000],  # Cap input size
        )
        return self.llm.generate(prompt=prompt, max_tokens=500, temperature=0.0)

    @staticmethod
    def _format_results(results: list[dict]) -> str:
        """Format search results into readable text."""
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            lines.append(f"[{i}] {title}\n{snippet}")
        return "\n\n".join(lines)

    @staticmethod
    def _default_search(query: str) -> list[dict]:
        """DuckDuckGo search via HTML API (FLEX-3: MVP default, replaceable)."""
        import httpx

        try:
            resp = httpx.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; Kaiwu/0.3)"},
                timeout=15.0,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return SearchAugmentorExpert._parse_ddg_html(resp.text)
        except Exception as e:
            logger.warning("DuckDuckGo search failed: %s", e)
            return []

    @staticmethod
    def _parse_ddg_html(html: str) -> list[dict]:
        """Parse DuckDuckGo HTML results (simple regex, no bs4 dependency)."""
        import re

        results = []
        # Extract result blocks
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        )
        titles = re.findall(
            r'class="result__a"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        )
        urls = re.findall(
            r'class="result__url"[^>]*href="([^"]*)"',
            html,
        )

        for i in range(min(len(titles), len(snippets), 10)):
            # Strip HTML tags
            title = re.sub(r"<[^>]+>", "", titles[i]).strip()
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            url = urls[i] if i < len(urls) else ""
            results.append({"title": title, "snippet": snippet, "url": url})

        return results
