from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
from urllib import parse, request

from shadowgen.config import AppConfig
from shadowgen.utils import retry


class Translator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def translate(self, text: str) -> str:
        backend = self.config.translator_backend

        if self.config.mock or backend == "mock":
            return self._mock_translate(text)

        if backend == "auto":
            return self._translate_auto(text)

        if backend in ("auto", "deepl"):
            deepl_key = os.getenv("DEEPL_API_KEY")
            if deepl_key:
                return retry(
                    operation=lambda: self._deepl_translate(text, deepl_key),
                    retries=self.config.retries,
                    base_delay=self.config.retry_base_delay,
                    task="deepl translation",
                )
            if backend == "deepl":
                raise RuntimeError("DEEPL_API_KEY is required for translator backend `deepl`.")

        if backend in ("auto", "openai"):
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                return self._openai_translate_with_policy(text, openai_key)
            if backend == "openai":
                raise RuntimeError("OPENAI_API_KEY is required for translator backend `openai`.")

        return self._mock_translate(text)

    def _translate_auto(self, text: str) -> str:
        deepl_key = os.getenv("DEEPL_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()

        providers: list[tuple[str, Callable[[], str]]] = []
        if deepl_key:
            providers.append(
                (
                    "deepl",
                    lambda: retry(
                        operation=lambda: self._deepl_translate(text, deepl_key),
                        retries=self.config.retries,
                        base_delay=self.config.retry_base_delay,
                        task="deepl translation",
                    ),
                )
            )
        if openai_key:
            providers.append(
                (
                    "openai",
                    lambda: self._openai_translate_with_policy(text, openai_key),
                )
            )

        if not providers:
            return self._mock_translate(text)

        if len(providers) == 1:
            _, fn = providers[0]
            return fn()

        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=len(providers)) as executor:
            futures = {executor.submit(fn): name for name, fn in providers}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    if result.strip():
                        return result
                    errors.append(f"{name}: empty translation result")
                except Exception as exc:  # pragma: no cover - runtime safety path
                    errors.append(f"{name}: {exc}")

        raise RuntimeError("All translation providers failed in auto mode: " + " | ".join(errors))

    def _openai_translate_with_policy(self, text: str, api_key: str) -> str:
        parallel = self._openai_parallel_requests()
        if parallel <= 1:
            return retry(
                operation=lambda: self._openai_translate(text, api_key),
                retries=self.config.retries,
                base_delay=self.config.retry_base_delay,
                task="openai translation",
            )
        return retry(
            operation=lambda: self._openai_translate_parallel_once(text, api_key, parallel),
            retries=self.config.retries,
            base_delay=self.config.retry_base_delay,
            task=f"openai parallel translation x{parallel}",
        )

    def _openai_translate_parallel_once(self, text: str, api_key: str, parallel: int) -> str:
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = [executor.submit(self._openai_translate, text, api_key) for _ in range(parallel)]
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result.strip():
                        return result
                    errors.append("empty translation result")
                except Exception as exc:  # pragma: no cover - runtime safety path
                    errors.append(str(exc))
        raise RuntimeError("all parallel OpenAI attempts failed: " + " | ".join(errors))

    @staticmethod
    def _openai_parallel_requests() -> int:
        raw = os.getenv("OPENAI_PARALLEL_REQUESTS", "1").strip()
        try:
            value = int(raw)
        except ValueError:
            return 1
        return max(1, value)

    def _openai_translate(self, text: str, api_key: str) -> str:
        from openai import OpenAI  # type: ignore

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        base_url = os.getenv("OPENAI_BASE_URL", "").strip()
        if base_url:
            client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a translation engine. Translate the user text only. "
                        "Return plain translated text without explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Translate to {self.config.target_lang}: {text}",
                },
            ],
        )
        return (response.choices[0].message.content or "").strip() or self._mock_translate(text)

    def _deepl_translate(self, text: str, api_key: str) -> str:
        data = parse.urlencode(
            {
                "auth_key": api_key,
                "text": text,
                "target_lang": self._map_target_lang_for_deepl(self.config.target_lang),
            }
        ).encode("utf-8")

        req = request.Request("https://api-free.deepl.com/v2/translate", data=data, method="POST")
        with request.urlopen(req, timeout=60) as resp:  # nosec B310
            body = resp.read().decode("utf-8")

        import json

        payload = json.loads(body)
        translations = payload.get("translations", [])
        if not translations:
            raise RuntimeError("DeepL returned no translation.")
        translated = str(translations[0].get("text", "")).strip()
        return translated or self._mock_translate(text)

    @staticmethod
    def _map_target_lang_for_deepl(lang: str) -> str:
        normalized = lang.strip().lower()
        if normalized in ("zh", "zh-cn", "zh-hans"):
            return "ZH"
        return normalized.upper()

    @staticmethod
    def _mock_translate(text: str) -> str:
        return f"【译】{text}"
