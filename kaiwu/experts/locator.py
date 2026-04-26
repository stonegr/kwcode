"""
Locator expert: hierarchical code location (file → function).
RED-2: Deterministic pipeline, no LLM self-decision on next step.
RED-3: Independent context window.
"""

import json
import logging
from typing import Optional

from kaiwu.core.context import TaskContext
from kaiwu.llm.llama_backend import LLMBackend
from kaiwu.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

LOCATOR_FILE_PROMPT = """你是代码定位专家。根据任务描述，从文件列表中找出最相关的文件。

仓库文件结构：
{file_tree}

任务描述：{task_description}

返回JSON，只包含最相关的文件（最多5个），格式：
{{"relevant_files": ["path/to/file1.py", "path/to/file2.py"]}}

只返回JSON，不要解释。"""

LOCATOR_FUNC_PROMPT = """你是代码定位专家。根据任务描述，找出代码中需要修改的函数名。

文件路径：{file_path}
文件内容：
```
{file_content}
```

任务描述：{task_description}

示例1：
任务："密码校验总是返回False"
代码中有 def verify_password(...) 和 def hash_password(...)
答案：{{"relevant_functions": ["verify_password"], "edit_locations": ["{file_path}:verify_password"]}}

示例2：
任务："分页total_count总是0"
代码中有 def paginate(...) 和 class PageResult
答案：{{"relevant_functions": ["paginate"], "edit_locations": ["{file_path}:paginate"]}}

现在请分析上面的代码，找出与任务最相关的函数。
注意：函数名必须是代码中 def xxx 或 class xxx 后面的名字，不要编造。

返回JSON：
{{"relevant_functions": ["函数名"], "edit_locations": ["{file_path}:函数名"]}}

只返回JSON，不要解释。"""


class LocatorExpert:
    """Two-phase locator: file-level → function-level. Each phase is one LLM call."""

    def __init__(self, llm: LLMBackend, tool_executor: ToolExecutor):
        self.llm = llm
        self.tools = tool_executor

    def run(self, ctx: TaskContext) -> Optional[dict]:
        """
        Phase 1: Locate relevant files (only sees file tree).
        Phase 2: Locate relevant functions (only sees file content).
        Returns dict with relevant_files, relevant_functions, edit_locations.
        """
        task_desc = f"{ctx.user_input}"
        if ctx.search_results:
            task_desc += f"\n\n参考信息：\n{ctx.search_results}"

        # Phase 1: File-level location
        file_tree = self.tools.get_file_tree(ctx.project_root)
        files = self._locate_files(file_tree, task_desc)
        if not files:
            logger.warning("Locator: no files found")
            return None

        # Phase 2: Function-level location for each file
        all_functions = []
        all_locations = []
        code_snippets = {}

        for fpath in files[:5]:  # Cap at 5 files
            content = self.tools.read_file(fpath)
            if content.startswith("[ERROR]"):
                continue

            funcs, locs = self._locate_functions(fpath, content, task_desc)
            all_functions.extend(funcs)
            all_locations.extend(locs)

            # Extract relevant code snippets (±20 lines around target)
            snippet = self._extract_snippet(content, funcs)
            if snippet:
                code_snippets[fpath] = snippet

        result = {
            "relevant_files": files,
            "relevant_functions": all_functions,
            "edit_locations": all_locations,
        }

        # Store snippets in context for Generator
        ctx.locator_output = result
        ctx.relevant_code_snippets = code_snippets
        return result

    def _locate_files(self, file_tree: str, task_desc: str) -> list[str]:
        """Phase 1: LLM call to find relevant files from tree."""
        prompt = LOCATOR_FILE_PROMPT.format(
            file_tree=file_tree[:4000],  # Truncate tree to fit context
            task_description=task_desc,
        )
        raw = self.llm.generate(prompt=prompt, max_tokens=300, temperature=0.0)
        return self._parse_file_list(raw)

    def _locate_functions(self, file_path: str, content: str, task_desc: str) -> tuple[list, list]:
        """Phase 2: LLM call to find relevant functions in a file."""
        # Truncate content to fit context (keep first 3000 chars + last 1000)
        if len(content) > 4000:
            content = content[:3000] + "\n... (truncated) ...\n" + content[-1000:]

        prompt = LOCATOR_FUNC_PROMPT.format(
            file_path=file_path,
            file_content=content,
            task_description=task_desc,
        )
        raw = self.llm.generate(prompt=prompt, max_tokens=300, temperature=0.0)
        return self._parse_func_result(raw)

    def _extract_snippet(self, content: str, functions: list[str]) -> str:
        """Extract code around target functions (±20 lines)."""
        if not functions:
            return content[:2000]  # Fallback: first 2000 chars

        lines = content.split("\n")
        collected = set()

        for func_name in functions:
            for i, line in enumerate(lines):
                if f"def {func_name}" in line or f"class {func_name}" in line:
                    start = max(0, i - 5)
                    end = min(len(lines), i + 40)
                    for j in range(start, end):
                        collected.add(j)

        if not collected:
            return content[:2000]

        sorted_lines = sorted(collected)
        result = []
        for idx in sorted_lines:
            result.append(f"{idx + 1:4d} | {lines[idx]}")
        return "\n".join(result)

    @staticmethod
    def _parse_file_list(raw: str) -> list[str]:
        """Parse file list JSON from LLM output."""
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                data = json.loads(raw[start:end + 1])
                return data.get("relevant_files", [])
        except (json.JSONDecodeError, KeyError):
            pass
        logger.warning("Locator file parse failed: %s", raw[:200])
        return []

    @staticmethod
    def _parse_func_result(raw: str) -> tuple[list, list]:
        """Parse function location JSON from LLM output."""
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                data = json.loads(raw[start:end + 1])
                return (
                    data.get("relevant_functions", []),
                    data.get("edit_locations", []),
                )
        except (json.JSONDecodeError, KeyError):
            pass
        logger.warning("Locator func parse failed: %s", raw[:200])
        return [], []
