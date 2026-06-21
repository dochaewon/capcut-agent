"""전사 세그먼트 → 컷 타임라인 자막.

핵심 2가지:
1) 시간 매핑: 전사는 '원본' 시간. 드래프트는 무음이 제거돼 당겨진 '컷' 타임라인.
   원본 시간 t를 컷 시간으로 매핑해야 자막이 영상과 맞는다.
2) 의존명사 청크: 줄바꿈을 의존명사('것/수/때/개/명'...) 앞에서 하지 않는다.
   (pycapcut-mac 스킬 참조) 화면에서 오타처럼 보이는 걸 막는다.
"""
from __future__ import annotations

from .silence import Segment

# 앞에서 줄을 끊으면 안 되는 의존명사·단위명사·조사성 조각
DEP_NOUNS = set(
    "것 수 때 줄 데 바 만큼 뿐 채 듯 지 등 점 개 명 번 원 시 분 초 살 일 달 년 "
    "가지 마리 권 장 대 잔 그루 송이 켤레 척".split()
)


def build_cut_mapper(keeps: list[Segment]):
    """원본시간 → 컷타임라인시간 매핑 함수와 컷 총길이를 돌려준다."""
    spans = []  # (orig_start, orig_end, cut_offset)
    acc = 0.0
    for k in keeps:
        spans.append((k.start, k.end, acc))
        acc += k.dur

    def to_cut(t: float) -> float:
        for s, e, off in spans:
            if t < s:        # 제거된 무음 안 → 다음 보존구간 시작으로 스냅
                return off
            if t <= e:       # 보존구간 안
                return off + (t - s)
        return acc           # 마지막 보존구간 뒤

    return to_cut, acc


def chunk_korean(text: str, max_chars: int = 16, max_lines: int = 2) -> str:
    """어절 단위로 줄바꿈하되 의존명사 앞에서는 끊지 않는다. 최대 2줄."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        # 의존명사는 앞 어절에 붙여 같은 줄 유지. 빈 줄이면 무조건 시작.
        must_attach = (cur == "") or (w in DEP_NOUNS)
        if not must_attach and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = w if cur == "" else f"{cur} {w}"
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:  # 넘치면 마지막 줄에 몰아 합침
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return "\n".join(lines)


def make_captions(segs: list[dict], keeps: list[Segment],
                  min_dur: float = 0.1, clean: bool = True) -> list[dict]:
    """전사 세그먼트를 컷 타임라인 자막으로 변환. [{start,dur,text}]

    clean=True면 자막 텍스트에서 잔말(음/어 등)을 제거한다.
    """
    from .filler import clean_caption_text
    to_cut, _ = build_cut_mapper(keeps)
    caps = []
    for s in segs:
        cs = to_cut(s["start"])
        ce = to_cut(s["end"])
        if ce - cs < min_dur:   # 무음·NG로 잘려 사라진 세그먼트는 버림
            continue
        text = clean_caption_text(s["text"]) if clean else s["text"]
        if not text.strip():
            continue
        caps.append({"start": cs, "dur": ce - cs,
                     "text": chunk_korean(text)})
    return caps
