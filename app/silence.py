"""ffmpeg silencedetect로 무음 구간을 찾고, 보존(발화) 구간으로 반전한다.

1단의 핵심: 단어 단위가 아니라 '무음 → 컷'이라는 가장 단순한 점프컷.
나중 단계(잔말/NG)는 전체 대본 위에서 결정하므로 여기서는 순수 무음만 다룬다.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class Segment:
    start: float  # 초
    end: float    # 초

    @property
    def dur(self) -> float:
        return self.end - self.start


def probe_duration(path: str) -> float:
    """ffprobe로 전체 길이(초)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


_RE_START = re.compile(r"silence_start:\s*([0-9.]+)")
_RE_END = re.compile(r"silence_end:\s*([0-9.]+)")
_RE_MEAN = re.compile(r"mean_volume:\s*(-?[0-9.]+)\s*dB")


def mean_volume_db(path: str) -> float:
    """ffmpeg volumedetect로 평균 음량(dB). 적응형 임계값 산출에 쓴다."""
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    m = _RE_MEAN.search(log)
    return float(m.group(1)) if m else -30.0


def auto_noise_db(path: str, margin: float = 3.0) -> float:
    """발화 평균보다 margin dB 위를 무음 임계로. 잡음 많은 footage(GoPro 등)에서
    고정 -30dB가 무음을 못 잡는 문제를 해결한다. (실측: mean -23.4 → 임계 -20.4)"""
    return round(mean_volume_db(path) + margin, 1)


def detect_silences(path: str, noise_db: float = -30.0, min_silence: float = 0.5) -> list[Segment]:
    """무음 구간 리스트. noise_db보다 조용하고 min_silence초 이상 지속된 구간."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    log = proc.stderr  # silencedetect는 stderr로 출력
    silences: list[Segment] = []
    cur_start: float | None = None
    for line in log.splitlines():
        m = _RE_START.search(line)
        if m:
            cur_start = float(m.group(1))
            continue
        m = _RE_END.search(line)
        if m and cur_start is not None:
            silences.append(Segment(cur_start, float(m.group(1))))
            cur_start = None
    return silences


def keep_segments(
    path: str,
    noise_db: float | None = None,
    min_silence: float = 0.5,
    pad: float = 0.10,
    min_keep: float = 0.20,
) -> tuple[list[Segment], float, float]:
    """보존(발화) 구간 리스트, 전체 길이, 실제 사용한 임계값(dB)을 돌려준다.

    noise_db=None 이면 영상 음량 분포에서 임계값을 자동 산출(auto_noise_db).
    pad: 각 발화 구간 양끝을 pad초씩 넓혀 어두(語頭)/어미가 잘리지 않게 한다.
    min_keep: 이보다 짧은 발화 조각은 잡음으로 보고 버린다.
    """
    if noise_db is None:
        noise_db = auto_noise_db(path)
    total = probe_duration(path)
    silences = detect_silences(path, noise_db, min_silence)

    # 무음의 여집합 = 발화 구간
    keeps: list[Segment] = []
    cursor = 0.0
    for s in silences:
        if s.start > cursor:
            keeps.append(Segment(cursor, s.start))
        cursor = max(cursor, s.end)
    if cursor < total:
        keeps.append(Segment(cursor, total))

    # 패딩 적용 후 클램프 + 짧은 조각 제거 + 겹침 병합
    padded: list[Segment] = []
    for k in keeps:
        seg = Segment(max(0.0, k.start - pad), min(total, k.end + pad))
        if padded and seg.start <= padded[-1].end:
            padded[-1].end = max(padded[-1].end, seg.end)  # 패딩으로 인접 조각이 겹치면 병합
        else:
            padded.append(seg)
    result = [k for k in padded if k.dur >= min_keep]
    return result, total, noise_db
