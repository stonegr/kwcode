"""
LLM backend: llama.cpp wrapper with Ollama-compatible HTTP fallback.
Provides a unified interface for all expert/gate LLM calls.
"""

import json
import logging
import os
import re
from typing import Optional

import httpx

from kaiwu.core.network import is_china_network

logger = logging.getLogger(__name__)

# Try importing llama_cpp; if unavailable, fall back to HTTP-only mode
try:
    from llama_cpp import Llama, LlamaGrammar
    HAS_LLAMA_CPP = True
except ImportError:
    HAS_LLAMA_CPP = False
    Llama = None
    LlamaGrammar = None


class LLMBackend:
    """Unified LLM interface supporting llama.cpp native and Ollama HTTP."""

    # Models known to use thinking/reasoning tokens that consume num_predict budget
    REASONING_MODELS = {"deepseek-r1", "qwq", "qwen3", "gemma4"}  # thinking/reasoning models
    # Multiplier for num_predict when using reasoning models
    REASONING_TOKEN_MULTIPLIER = 8

    # ModelScope model mapping for China network auto-switching
    MODELSCOPE_MODELS = {
        "deepseek-r1:8b": "deepseek-ai/DeepSeek-R1-Distill-Qwen-8B",
        "qwen3:8b": "Qwen/Qwen3-8B",
        "qwen3:14b": "Qwen/Qwen3-14B",
        "gemma3:4b": "google/gemma-3-4b-it",
    }

    def __init__(
        self,
        model_path: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "qwen3-8b",
        n_ctx: int = 8192,
        n_gpu_layers: int = -1,
        verbose: bool = False,
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.ollama_model = ollama_model
        self.verbose = verbose
        self._llm: Optional[object] = None
        self._mode = "none"
        self._is_reasoning = self._detect_reasoning_model(ollama_model)

        # Prefer native llama.cpp if model_path provided and library available
        if model_path and HAS_LLAMA_CPP:
            try:
                self._llm = Llama(
                    model_path=model_path,
                    n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers,
                    verbose=verbose,
                )
                self._mode = "llama_cpp"
                logger.info("LLM backend: llama.cpp native (model=%s)", model_path)
                return
            except Exception as e:
                logger.warning("llama.cpp init failed: %s, falling back to Ollama", e)

        # Fallback: Ollama HTTP API
        self._mode = "ollama"
        logger.info("LLM backend: Ollama HTTP (%s, model=%s)", self.ollama_url, self.ollama_model)

    @property
    def mode(self) -> str:
        return self._mode

    def ensure_model_available(self) -> None:
        """Check if model is pulled in Ollama; auto-switch to ModelScope on China networks."""
        if self._mode != "ollama":
            return

        # Query Ollama for available models
        try:
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=10.0)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
        except Exception as e:
            logger.warning("无法查询 Ollama 模型列表: %s", e)
            return

        # Check if current model is already available
        # Ollama tags list includes full "name:tag" entries; match exactly or
        # treat a tagless request (e.g. "qwen3") as matching "qwen3:latest".
        target = self.ollama_model
        for m in models:
            if m == target or m == f"{target}:latest":
                logger.debug("模型 %s 已存在于 Ollama", self.ollama_model)
                return

        # Model not found — try ModelScope if on China network
        if self.ollama_model not in self.MODELSCOPE_MODELS:
            logger.info("模型 %s 未找到，且不在 ModelScope 映射表中，跳过自动切换", self.ollama_model)
            return

        if not is_china_network():
            logger.debug("模型 %s 未找到，非国内网络，使用默认源拉取", self.ollama_model)
            return

        logger.info("模型未找到，检测到国内网络，尝试从 ModelScope 拉取...")
        os.environ["OLLAMA_MODELS"] = "https://modelscope.cn/models"
        logger.info("已设置 OLLAMA_MODELS=%s", os.environ["OLLAMA_MODELS"])

    def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.0,
        stop: Optional[list[str]] = None,
        grammar_str: Optional[str] = None,
    ) -> str:
        """Generate text completion. Returns raw string output."""
        if self._mode == "llama_cpp":
            return self._generate_native(prompt, system, max_tokens, temperature, stop, grammar_str)
        return self._generate_ollama(prompt, system, max_tokens, temperature, stop)

    def _generate_native(
        self, prompt: str, system: str, max_tokens: int,
        temperature: float, stop: Optional[list[str]], grammar_str: Optional[str],
    ) -> str:
        kwargs: dict = {
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop:
            kwargs["stop"] = stop
        if grammar_str and LlamaGrammar:
            kwargs["grammar"] = LlamaGrammar.from_string(grammar_str)

        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        resp = self._llm(full_prompt, **kwargs)
        return resp["choices"][0]["text"].strip()

    def _generate_ollama(
        self, prompt: str, system: str, max_tokens: int,
        temperature: float, stop: Optional[list[str]],
    ) -> str:
        # Always use /api/chat for Ollama — reasoning models (deepseek-r1 etc.)
        # consume num_predict budget with thinking tokens in /api/generate,
        # returning empty responses. /api/chat separates thinking from content.
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._chat_ollama(messages, max_tokens, temperature, stop)

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Strip <think>...</think> blocks from reasoning models (e.g. deepseek-r1)."""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return cleaned if cleaned else text

    def chat(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.0,
        stop: Optional[list[str]] = None,
        grammar_str: Optional[str] = None,
    ) -> str:
        """Chat-style completion (for Ollama /api/chat or converted to prompt for llama.cpp)."""
        if self._mode == "ollama":
            return self._chat_ollama(messages, max_tokens, temperature, stop)

        # Convert messages to single prompt for llama.cpp
        system = ""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system = content
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
        prompt_parts.append("Assistant:")
        prompt = "\n".join(prompt_parts)
        return self._generate_native(prompt, system, max_tokens, temperature, stop, grammar_str)

    def _chat_ollama(
        self, messages: list[dict], max_tokens: int,
        temperature: float, stop: Optional[list[str]],
    ) -> str:
        effective_tokens = max_tokens
        effective_temp = temperature
        think_enabled = True  # Default: let model think

        if self._is_reasoning:
            # Short-output tasks (Gate, Locator selection) don't need deep reasoning.
            # Disable thinking to save 50-80% latency on classification tasks.
            if max_tokens <= 500:
                think_enabled = False
                # No multiplier needed when thinking is off
            else:
                effective_tokens = max_tokens * self.REASONING_TOKEN_MULTIPLIER

            if temperature == 0.0:
                effective_temp = 0.01

        payload = {
            "model": self.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": effective_tokens,
                "temperature": effective_temp,
            },
        }

        # Disable thinking for short classification tasks on reasoning models
        if self._is_reasoning and not think_enabled:
            payload["think"] = False

        # Don't pass stop sequences to reasoning models with thinking enabled
        if stop and (not self._is_reasoning or not think_enabled):
            payload["options"]["stop"] = stop

        try:
            resp = httpx.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=180.0,
            )
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip()
            return self._strip_thinking(raw)
        except Exception as e:
            logger.error("Ollama chat failed: %s", e)
            raise

    @classmethod
    def _detect_reasoning_model(cls, model_name: str) -> bool:
        """Detect if model uses thinking/reasoning tokens."""
        name_lower = model_name.lower().split(":")[0]  # strip tag like :8b
        return any(r in name_lower for r in cls.REASONING_MODELS)
