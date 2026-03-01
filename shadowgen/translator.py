from __future__ import annotations

import os
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
                return retry(
                    operation=lambda: self._openai_translate(text, openai_key),
                    retries=self.config.retries,
                    base_delay=self.config.retry_base_delay,
                    task="openai translation",
                )
            if backend == "openai":
                raise RuntimeError("OPENAI_API_KEY is required for translator backend `openai`.")

        return self._mock_translate(text)

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
