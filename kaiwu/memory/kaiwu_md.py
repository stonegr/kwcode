"""
KAIWU.md memory system: project-level persistent memory.
Reads on task start, writes on task success.
FLEX-4: If context injection exceeds 50% of model window, truncate to file paths + expert types only.
"""

import logging
import os
import re
from datetime import datetime
from typing import Optional

from kaiwu.core.context import TaskContext

logger = logging.getLogger(__name__)

KAIWU_MD_TEMPLATE = """# KAIWU 项目记忆
> 自动生成，由Kaiwu维护，请勿手动删除

## 项目信息
- 语言：{language}
- 框架：{framework}
- 测试命令：{test_cmd}
- 主要入口：{entry_point}

## 成功任务记录
| 时间 | 任务类型 | 涉及文件 | 专家序列 |
|------|---------|---------|---------|

## 已知模式
"""

MAX_RECORDS = 50
MAX_INJECT_CHARS = 2000  # Approximate char limit for context injection


class KaiwuMemory:
    """KAIWU.md read/write manager."""

    def __init__(self):
        pass

    def load(self, project_root: str) -> str:
        """
        Load KAIWU.md and return injectable context string.
        Only injects '## 项目信息' and '## 已知模式' sections.
        """
        md_path = os.path.join(project_root, "KAIWU.md")
        if not os.path.exists(md_path):
            return ""

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.warning("Failed to read KAIWU.md: %s", e)
            return ""

        # Extract relevant sections only
        project_info = self._extract_section(content, "## 项目信息")
        known_patterns = self._extract_section(content, "## 已知模式")

        injectable = ""
        if project_info:
            injectable += f"项目信息：\n{project_info}\n"
        if known_patterns:
            injectable += f"已知模式：\n{known_patterns}\n"

        # FLEX-4: Truncate if too large
        if len(injectable) > MAX_INJECT_CHARS:
            injectable = injectable[:MAX_INJECT_CHARS] + "\n...(记忆已截断)"

        return injectable

    def save(self, project_root: str, ctx: TaskContext):
        """
        Append successful task record to KAIWU.md.
        Only writes when Verifier passed.
        """
        if not ctx.verifier_output or not ctx.verifier_output.get("passed"):
            return

        md_path = os.path.join(project_root, "KAIWU.md")

        # Create KAIWU.md if it doesn't exist
        if not os.path.exists(md_path):
            self._init_kaiwu_md(md_path, ctx)
            return

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.warning("Failed to read KAIWU.md for save: %s", e)
            return

        # Build new record line
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        expert_type = ctx.gate_result.get("expert_type", "unknown")
        files = []
        if ctx.locator_output:
            files = ctx.locator_output.get("relevant_files", [])
        elif ctx.generator_output:
            files = [p.get("file", "") for p in ctx.generator_output.get("patches", [])]
        files_str = ", ".join(files[:3]) if files else "N/A"

        # Determine expert sequence used
        from kaiwu.core.orchestrator import EXPERT_SEQUENCES
        seq = EXPERT_SEQUENCES.get(expert_type, ["generator"])
        seq_str = "→".join([s.capitalize() for s in seq])

        new_record = f"| {now} | {expert_type} | {files_str} | {seq_str} |"

        # Insert record after table header
        table_marker = "| 时间 | 任务类型 | 涉及文件 | 专家序列 |"
        separator = "|------|---------|---------|---------|"

        if separator in content:
            # Insert after separator line
            parts = content.split(separator, 1)
            existing_records = parts[1] if len(parts) > 1 else ""

            # Count existing records and enforce MAX_RECORDS
            record_lines = [
                line for line in existing_records.strip().split("\n")
                if line.startswith("|") and "时间" not in line and "---" not in line
            ]
            if len(record_lines) >= MAX_RECORDS:
                # Remove oldest records (first in list)
                record_lines = record_lines[-(MAX_RECORDS - 1):]

            record_lines.append(new_record)
            new_records = "\n".join(record_lines)

            content = parts[0] + separator + "\n" + new_records + "\n"

            # Preserve known patterns section
            patterns_section = self._extract_section(parts[1] if len(parts) > 1 else "", "## 已知模式")
            if patterns_section:
                content += f"\n## 已知模式\n{patterns_section}\n"
            elif "## 已知模式" not in content:
                content += "\n## 已知模式\n"
        else:
            # Malformed file, append record
            content += f"\n{new_record}\n"

        # Update project info if we learned something new
        content = self._update_project_info(content, ctx)

        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("Saved task record to KAIWU.md")
        except Exception as e:
            logger.warning("Failed to write KAIWU.md: %s", e)

    def init(self, project_root: str) -> str:
        """Initialize KAIWU.md with auto-detected project info."""
        md_path = os.path.join(project_root, "KAIWU.md")
        if os.path.exists(md_path):
            return f"KAIWU.md already exists at {md_path}"

        # Auto-detect project info
        language = self._detect_language(project_root)
        framework = self._detect_framework(project_root)
        test_cmd = self._detect_test_cmd(project_root)
        entry_point = self._detect_entry(project_root)

        content = KAIWU_MD_TEMPLATE.format(
            language=language,
            framework=framework,
            test_cmd=test_cmd,
            entry_point=entry_point,
        )

        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Created KAIWU.md at {md_path}"
        except Exception as e:
            return f"Failed to create KAIWU.md: {e}"

    def show(self, project_root: str) -> str:
        """Return KAIWU.md content for display."""
        md_path = os.path.join(project_root, "KAIWU.md")
        if not os.path.exists(md_path):
            return "KAIWU.md not found. Run `kaiwu init` to create."
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Failed to read KAIWU.md: {e}"

    def _init_kaiwu_md(self, md_path: str, ctx: TaskContext):
        """Create KAIWU.md from first successful task."""
        language = self._detect_language(ctx.project_root)
        framework = self._detect_framework(ctx.project_root)
        test_cmd = self._detect_test_cmd(ctx.project_root)
        entry_point = self._detect_entry(ctx.project_root)

        content = KAIWU_MD_TEMPLATE.format(
            language=language,
            framework=framework,
            test_cmd=test_cmd,
            entry_point=entry_point,
        )

        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.warning("Failed to init KAIWU.md: %s", e)

    @staticmethod
    def _extract_section(content: str, header: str) -> str:
        """Extract content between a ## header and the next ## header."""
        pattern = re.escape(header) + r"\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _update_project_info(content: str, ctx: TaskContext) -> str:
        """Update project info section if we detected new info."""
        # Simple heuristic: if files suggest a framework, update
        files = []
        if ctx.locator_output:
            files = ctx.locator_output.get("relevant_files", [])

        for f in files:
            if "fastapi" in f.lower() or "app.py" in f.lower():
                if "未检测" in content:
                    content = content.replace("框架：未检测", "框架：FastAPI")
            if "django" in f.lower() or "manage.py" in f.lower():
                if "未检测" in content:
                    content = content.replace("框架：未检测", "框架：Django")
            if "flask" in f.lower():
                if "未检测" in content:
                    content = content.replace("框架：未检测", "框架：Flask")

        return content

    @staticmethod
    def _detect_language(project_root: str) -> str:
        """Detect primary language from file extensions."""
        ext_count: dict[str, int] = {}
        try:
            for root, dirs, files in os.walk(project_root):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv")]
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in (".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".c"):
                        ext_count[ext] = ext_count.get(ext, 0) + 1
        except Exception:
            pass

        if not ext_count:
            return "未检测"

        top_ext = max(ext_count, key=ext_count.get)
        lang_map = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".go": "Go", ".rs": "Rust", ".java": "Java", ".cpp": "C++", ".c": "C",
        }
        return lang_map.get(top_ext, "未检测")

    @staticmethod
    def _detect_framework(project_root: str) -> str:
        """Detect framework from dependency files."""
        indicators = {
            "requirements.txt": {"fastapi": "FastAPI", "django": "Django", "flask": "Flask"},
            "pyproject.toml": {"fastapi": "FastAPI", "django": "Django", "flask": "Flask"},
            "package.json": {"react": "React", "vue": "Vue", "next": "Next.js", "express": "Express"},
            "go.mod": {"gin": "Gin", "echo": "Echo", "fiber": "Fiber"},
        }
        for dep_file, frameworks in indicators.items():
            fpath = os.path.join(project_root, dep_file)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read().lower()
                    for keyword, name in frameworks.items():
                        if keyword in content:
                            return name
                except Exception:
                    pass
        return "未检测"

    @staticmethod
    def _detect_test_cmd(project_root: str) -> str:
        """Detect test command."""
        if os.path.exists(os.path.join(project_root, "pytest.ini")) or \
           os.path.exists(os.path.join(project_root, "pyproject.toml")):
            return "pytest"
        if os.path.exists(os.path.join(project_root, "package.json")):
            return "npm test"
        return "未检测"

    @staticmethod
    def _detect_entry(project_root: str) -> str:
        """Detect main entry point."""
        candidates = ["main.py", "app.py", "src/main.py", "src/app.py", "index.js", "index.ts", "main.go"]
        for c in candidates:
            if os.path.exists(os.path.join(project_root, c)):
                return c
        return "未检测"
