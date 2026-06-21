"""4단: 잔말(filler) + NG 컷 — 전체 대본 위에서 판단.

원칙(스펙): 단어 하나만 보고 즉흥 판단하지 않고 '대본 전체'를 근거로 결정.
안전 위주 — 실제 말을 잘못 자르면 치명적이므로 모호한 건 남긴다.

- filler: 비어휘적 추임새(음/어/에/흠 등)만 단어 타이밍으로 제거. 의미 있는
  단어(아/그/저/뭐/좀/약간 등)는 기본 제외(오컷 위험). FILLERS로 튜닝.
- NG: 말을 더듬고 같은 문장을 다시 말한 경우 → 앞(실패) 테이크를 제거.
  인접 세그먼트 텍스트 유사도로 탐지.
"""
from __future__ import annotations

import difflib
import re

from .silence import Segment

# 비어휘적 망설임 소리만 (거의 항상 잔말). 보수적으로 시작, 필요시 확장.
FILLERS = {
    "음", "음음", "으음", "으", "흠", "엄", "어", "어어", "어어어",
    "에", "에에", "그-", "저-",
}

_PUNCT = re.compile(r"[\s.,!?~…\-]+$")


def _norm(word: str) -> str:
    return _PUNCT.sub("", word.strip())


def _is_filler(word: str) -> bool:
    w = _norm(word)
    if w in FILLERS:
        return True
    # 단일 모음/자음의 길게 늘인 형태(어어어/으으/음~)도 잔말로 본다
    return len(w) >= 2 and len(set(w)) == 1 and w[0] in "음어으에흠아오우"


def filler_spans(segments: list[dict], min_dur: float = 0.12) -> list[tuple[float, float]]:
    """잔말 단어들의 (start,end) 원본시간 구간."""
    spans = []
    for s in segments:
        for w in s.get("words", []):
            if _is_filler(w["word"]):
                a, b = float(w["start"]), float(w["end"])
                if b - a >= min_dur:
                    spans.append((a, b))
    return spans


def ng_spans(segments: list[dict], sim_threshold: float = 0.82) -> list[tuple[float, float]]:
    """더듬어 다시 말한 NG 테이크 구간. 인접 세그먼트가 매우 유사하면 앞 것을 제거."""
    spans = []
    for i in range(len(segments) - 1):
        a, b = segments[i], segments[i + 1]
        ta, tb = a["text"], b["text"]
        if len(ta) < 4:
            continue
        ratio = difflib.SequenceMatcher(None, ta, tb).ratio()
        if ratio >= sim_threshold:
            spans.append((float(a["start"]), float(a["end"])))  # 앞(실패) 테이크 제거
    return spans


def remove_spans(segments: list[dict],
                 do_filler: bool = True, do_ng: bool = True) -> list[tuple[float, float]]:
    """제거할 (start,end) 구간 전체 (잔말 + NG), 병합 정렬."""
    spans = []
    if do_filler:
        spans += filler_spans(segments)
    if do_ng:
        spans += ng_spans(segments)
    if not spans:
        return []
    spans.sort()
    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def subtract(keeps: list[Segment], removals: list[tuple[float, float]],
             min_keep: float = 0.20) -> list[Segment]:
    """보존 구간(keeps)에서 제거 구간(removals)을 빼낸 새 보존 구간."""
    if not removals:
        return keeps
    result: list[Segment] = []
    for k in keeps:
        cur = k.start
        for rs, re_ in removals:
            if re_ <= cur or rs >= k.end:
                continue
            if rs > cur:
                result.append(Segment(cur, min(rs, k.end)))
            cur = max(cur, re_)
            if cur >= k.end:
                break
        if cur < k.end:
            result.append(Segment(cur, k.end))
    return [s for s in result if s.dur >= min_keep]


def clean_caption_text(text: str) -> str:
    """자막에서 잔말 토큰 제거 (화면 텍스트 정리)."""
    kept = [w for w in text.split() if not _is_filler(w)]
    return " ".join(kept)
