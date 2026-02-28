from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from shadowgen.utils import logger


def load_env_file(filename: str = ".env") -> bool:
    env_path = Path.cwd() / filename
    if not env_path.exists():
        return False
    loaded = load_dotenv(dotenv_path=env_path, override=False)
    if loaded:
        logger.debug("Loaded environment variables from %s", env_path)
    return loaded
