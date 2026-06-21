"""한 영상 분석 파이프라인 (silence → asr → filler) — 재사용 단위.

build 단계를 뺀 '계산'만: 보존 구간(keeps) + 자막(captions) + 원본 길이.
batch / merge / cut 가 공유한다.
"""
from __future__ import annotations

from .captions import make_captions
from .filler import remove_spans, subtract
from .silence import Segment, keep_segments


def analyze(path: str, noise: float | None = None, silence: float = 0.5,
            pad: float = 0.1, subs: bool = True, filler: bool = True
            ) -> tuple[list[Segment], list[dict] | None, float]:
    """returns (keeps, captions, total_seconds). captions는 컷 타임라인(0기준)."""
    keeps, total, _ = keep_segments(path, noise_db=noise, min_silence=silence, pad=pad)
    caps = None
    if subs:
        from .asr import transcribe_sync  # 지연 import (mlx 무거움)
        segs = transcribe_sync(path)
        if filler:
            keeps = subtract(keeps, remove_spans(segs))
        caps = make_captions(segs, keeps)
    return keeps, caps, total
