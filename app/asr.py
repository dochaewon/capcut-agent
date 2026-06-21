"""3단: mlx-whisper(트랙 A) 음성 인식.

원칙(스펙): 전체 대본을 먼저 추출한다. 자막/NG 판단은 그 위에서.
- ASR_LOCK으로 직렬화 (numba/mlx 동시호출 비안전). pycapcut-mac 스킬 참조.
- content hash 캐시 (mtime 아님 — 재업로드 시 mtime은 매번 miss).
- whisper 호출은 worker thread에서 (이벤트 루프 블로킹 방지).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os

# 한국어 균형(품질/속도): large-v3-turbo. 첫 실행 시 모델 자동 다운로드(~1.5GB).
MODEL = "mlx-community/whisper-large-v3-turbo"

ASR_LOCK = asyncio.Lock()
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache", "asr")


# 캐시 스키마 버전. 전사 출력 형식이 바뀌면 올려 옛 캐시를 무효화한다.
_CACHE_VER = "v2-words"


def _content_key(path: str) -> str:
    """파일 내용 + 모델 + 스키마버전으로 캐시 키 (mtime 비의존)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    h.update(MODEL.encode())
    h.update(_CACHE_VER.encode())
    return h.hexdigest()[:16]


def _run_whisper(path: str) -> list[dict]:
    import mlx_whisper  # 지연 import (무거움)
    # word_timestamps: 단어별 타이밍 → 4단 잔말(filler) 단어 컷에 필요
    r = mlx_whisper.transcribe(path, path_or_hf_repo=MODEL,
                               language="ko", word_timestamps=True)
    out = []
    for s in r["segments"]:
        text = s["text"].strip()
        if not text:
            continue
        words = [{"word": w["word"].strip(),
                  "start": float(w["start"]), "end": float(w["end"])}
                 for w in s.get("words", []) if w.get("word", "").strip()]
        out.append({"start": float(s["start"]), "end": float(s["end"]),
                    "text": text, "words": words})
    return out


def transcribe_sync(path: str) -> list[dict]:
    """전사 결과(세그먼트 리스트). 캐시 우선."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(_CACHE_DIR, _content_key(path) + ".json")
    if os.path.isfile(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    segs = _run_whisper(path)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False)
    return segs


async def transcribe(path: str) -> list[dict]:
    """ASR_LOCK으로 직렬화된 비동기 전사."""
    async with ASR_LOCK:
        return await asyncio.to_thread(transcribe_sync, path)
