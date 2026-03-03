from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_input_fingerprint(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class ResumeManager:
    state_path: Path
    input_payload: dict[str, Any]
    fingerprint: str
    state: dict[str, Any]

    @classmethod
    def create(cls, state_path: Path, input_payload: dict[str, Any]) -> "ResumeManager":
        fingerprint = build_input_fingerprint(input_payload)
        state = {
            "version": 1,
            "input_fingerprint": fingerprint,
            "input_summary": input_payload,
            "updated_at": _utc_now_iso(),
            "stage": "init",
            "title": "",
            "artifacts": {},
            "chunks_total": 0,
            "chunks_done": [],
            "chunks": {},
            "last_error": "",
            "last_failed_chunk": 0,
        }
        return cls(state_path=state_path, input_payload=input_payload, fingerprint=fingerprint, state=state)

    def load_or_initialize(self, require_match: bool) -> None:
        if not self.state_path.exists():
            self._write_state()
            return

        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        existing_fingerprint = str(payload.get("input_fingerprint", "")).strip()
        if require_match and existing_fingerprint and existing_fingerprint != self.fingerprint:
            raise RuntimeError(
                "Existing resume state does not match current input. "
                "Use same parameters or run without --resume."
            )

        if not require_match and existing_fingerprint and existing_fingerprint != self.fingerprint:
            self._write_state()
            return

        self.state = payload
        self.state["input_fingerprint"] = self.fingerprint
        self.state["input_summary"] = self.input_payload
        self.touch()

    def touch(self) -> None:
        self.state["updated_at"] = _utc_now_iso()
        self._write_state()

    def set_stage(self, stage: str) -> None:
        self.state["stage"] = stage
        self.touch()

    def set_title(self, title: str) -> None:
        self.state["title"] = title
        self.touch()

    def get_title(self) -> str:
        return str(self.state.get("title", "")).strip()

    def set_artifact(self, key: str, value: str) -> None:
        artifacts = self.state.setdefault("artifacts", {})
        artifacts[key] = value
        self.touch()

    def get_artifact(self, key: str) -> str:
        artifacts = self.state.get("artifacts", {})
        return str(artifacts.get(key, "")).strip()

    def init_chunks(self, chunks: list[dict[str, Any]]) -> None:
        existing = self.state.setdefault("chunks", {})
        for c in chunks:
            cid = str(c["id"])
            existing.setdefault(
                cid,
                {
                    "id": c["id"],
                    "start": c["start"],
                    "end": c["end"],
                    "text": c["text"],
                    "status": "pending",
                    "translation": "",
                    "tts_path": "",
                    "tts_duration": 0.0,
                    "error": "",
                },
            )
        self.state["chunks_total"] = len(chunks)
        done = []
        for cid, payload in existing.items():
            if payload.get("status") == "done":
                done.append(int(cid))
        self.state["chunks_done"] = sorted(done)
        self.touch()

    def get_chunk_done(self, chunk_id: int) -> dict[str, Any] | None:
        payload = self.state.get("chunks", {}).get(str(chunk_id))
        if not isinstance(payload, dict):
            return None
        if payload.get("status") != "done":
            return None
        return payload

    def mark_chunk_done(
        self,
        chunk_id: int,
        translation: str,
        tts_path: str,
        tts_duration: float,
    ) -> None:
        chunks = self.state.setdefault("chunks", {})
        record = chunks.setdefault(str(chunk_id), {"id": chunk_id})
        record.update(
            {
                "status": "done",
                "translation": translation,
                "tts_path": tts_path,
                "tts_duration": tts_duration,
                "error": "",
            }
        )
        done = set(int(x) for x in self.state.get("chunks_done", []))
        done.add(chunk_id)
        self.state["chunks_done"] = sorted(done)
        self.state["last_failed_chunk"] = 0
        self.state["last_error"] = ""
        self.touch()

    def mark_chunk_failed(self, chunk_id: int, error: str) -> None:
        chunks = self.state.setdefault("chunks", {})
        record = chunks.setdefault(str(chunk_id), {"id": chunk_id})
        record.update({"status": "failed", "error": error})
        self.state["last_failed_chunk"] = chunk_id
        self.state["last_error"] = error[:2000]
        self.touch()

    def set_error(self, error: str) -> None:
        self.state["last_error"] = error[:2000]
        self.touch()

    def _write_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.state_path)
