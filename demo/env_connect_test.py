from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib import parse, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shadowgen.env_loader import load_env_file


def _mask(secret: str, keep: int = 4) -> str:
    if not secret:
        return "<empty>"
    if len(secret) <= keep * 2:
        return "*" * len(secret)
    return f"{secret[:keep]}...{secret[-keep:]}"


def test_openai() -> bool:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()

    if not key:
        print("[openai] OPENAI_API_KEY is empty, skip.")
        return False

    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover
        print(f"[openai] openai package not available: {exc}")
        return False

    print(f"[openai] key={_mask(key)} model={model}")
    print(f"[openai] base_url={base_url or '<default>'}")

    try:
        if base_url:
            client = OpenAI(api_key=key, base_url=base_url)
        else:
            client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=8,
            messages=[{"role": "user", "content": "Reply with OK only."}],
        )
        content = (resp.choices[0].message.content or "").strip()
        print(f"[openai] success: {content!r}")
        return True
    except Exception as exc:
        print(f"[openai] failed: {exc}")
        return False


def test_deepl() -> bool:
    key = os.getenv("DEEPL_API_KEY", "").strip()
    if not key:
        print("[deepl] DEEPL_API_KEY is empty, skip.")
        return False

    print(f"[deepl] key={_mask(key)} endpoint=https://api-free.deepl.com/v2/translate")
    data = parse.urlencode(
        {
            "auth_key": key,
            "text": "hello world",
            "target_lang": "ZH",
        }
    ).encode("utf-8")
    req = request.Request("https://api-free.deepl.com/v2/translate", data=data, method="POST")

    try:
        with request.urlopen(req, timeout=30) as resp:  # nosec B310
            body = resp.read().decode("utf-8")
        payload = json.loads(body)
        translated = payload.get("translations", [{}])[0].get("text", "")
        print(f"[deepl] success: {translated!r}")
        return True
    except Exception as exc:
        print(f"[deepl] failed: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal API connectivity test with .env")
    parser.add_argument(
        "--provider",
        choices=("all", "openai", "deepl"),
        default="all",
        help="Provider to test.",
    )
    args = parser.parse_args()

    loaded = load_env_file()
    print(f".env loaded: {loaded}")

    ok = True
    if args.provider in ("all", "openai"):
        ok = test_openai() and ok
    if args.provider in ("all", "deepl"):
        ok = test_deepl() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
