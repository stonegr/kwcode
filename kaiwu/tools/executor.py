"""
Tool executor: self-implemented per FLEX-1 fallback.
Provides read_file, write_file, run_bash, list_dir, git_commit.
Interface is fixed (RED-4: transparent to user).
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Deterministic tool execution layer. No LLM involved."""

    def __init__(self, project_root: str = "."):
        self.project_root = os.path.abspath(project_root)

    def read_file(self, path: str) -> str:
        """Read file content. Path can be relative to project_root or absolute."""
        full = self._resolve(path)
        try:
            with open(full, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"[ERROR] File not found: {full}"
        except Exception as e:
            return f"[ERROR] Read failed: {e}"

    def write_file(self, path: str, content: str) -> bool:
        """Write content to file. Creates parent dirs if needed."""
        full = self._resolve(path)
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("Wrote %d bytes to %s", len(content), full)
            return True
        except Exception as e:
            logger.error("Write failed: %s", e)
            return False

    def run_bash(self, command: str, cwd: Optional[str] = None, timeout: int = 60) -> tuple[str, str, int]:
        """
        Run a shell command. Returns (stdout, stderr, returncode).
        Timeout in seconds (default 60).
        """
        work_dir = cwd or self.project_root
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", f"[ERROR] Command timed out after {timeout}s", -1
        except Exception as e:
            return "", f"[ERROR] {e}", -1

    def list_dir(self, path: str = ".") -> list[str]:
        """List directory contents. Returns sorted list of names."""
        full = self._resolve(path)
        try:
            entries = os.listdir(full)
            return sorted(entries)
        except FileNotFoundError:
            return [f"[ERROR] Directory not found: {full}"]
        except Exception as e:
            return [f"[ERROR] {e}"]

    def git_commit(self, message: str, cwd: Optional[str] = None) -> bool:
        """Stage all changes and commit."""
        work_dir = cwd or self.project_root
        _, err1, rc1 = self.run_bash("git add -A", cwd=work_dir)
        if rc1 != 0:
            logger.error("git add failed: %s", err1)
            return False
        _, err2, rc2 = self.run_bash(f'git commit -m "{message}"', cwd=work_dir)
        if rc2 != 0:
            logger.error("git commit failed: %s", err2)
            return False
        return True

    def get_file_tree(self, path: str = ".", max_depth: int = 3, max_files: int = 200) -> str:
        """Generate a file tree string for Locator context injection."""
        root = self._resolve(path)
        lines = []
        count = 0
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden dirs and common noise
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "venv", ".venv")
            ]
            depth = dirpath.replace(root, "").count(os.sep)
            if depth >= max_depth:
                dirnames.clear()
                continue
            indent = "  " * depth
            dirname = os.path.basename(dirpath) or os.path.basename(root)
            lines.append(f"{indent}{dirname}/")
            for fname in sorted(filenames):
                if count >= max_files:
                    lines.append(f"{indent}  ... (truncated at {max_files} files)")
                    return "\n".join(lines)
                lines.append(f"{indent}  {fname}")
                count += 1
        return "\n".join(lines)

    def apply_patch(self, file_path: str, original: str, modified: str) -> bool:
        """Apply a text replacement patch. Exact match only — original is read from file."""
        full = self._resolve(file_path)
        try:
            content = self.read_file(file_path)
            if content.startswith("[ERROR]"):
                return False
            if original not in content:
                logger.warning("Original text not found in %s", full)
                return False
            new_content = content.replace(original, modified, 1)
            return self.write_file(file_path, new_content)
        except Exception as e:
            logger.error("Patch apply failed: %s", e)
            return False

    def _resolve(self, path: str) -> str:
        """Resolve path relative to project_root."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.project_root, path)
