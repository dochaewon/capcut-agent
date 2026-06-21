"""보존 구간 리스트 → 캡컷 점프컷 드래프트.

pycapcut-mac 스킬의 1번 함정: 시간은 전부 마이크로초. trange의 2번째 인자는
duration(끝시간 아님). 숫자를 그냥 넘기면 초가 µs로 오해되므로 us()로 변환해 넘긴다.
"""
from __future__ import annotations

import os
import shutil

import pycapcut as cc
from pycapcut import trange

from .capcut_compat import make_capcut_openable, register_in_root_meta
from .config import capcut_draft_dir
from .silence import Segment


def us(sec: float) -> int:
    """초 → 마이크로초 정수. (pycapcut에 숫자를 넘길 땐 항상 µs)"""
    return int(round(sec * 1_000_000))


# 자막 스타일 (브이로그 톤: 작고 가늘게, 얇은 외곽선). 한 곳에서 튜닝.
CAPTION_SIZE = 5.0          # 글자 크기 (기본 8.0은 너무 큼)
CAPTION_BORDER_WIDTH = 6.0  # 외곽선 두께 (기본 40, 20도 굵어 보임)
CAPTION_BORDER_ALPHA = 0.7  # 외곽선 반투명 → 덜 묵직하게
CAPTION_Y = -0.82           # 화면 하단 (음수=아래)


def build_jumpcut_draft(
    video_path: str,
    keeps: list[Segment],
    draft_name: str,
    captions: list[dict] | None = None,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> tuple[str, float]:
    """보존 구간들을 타임라인에 순차로 이어붙인 드래프트를 만들고 저장한다.

    각 보존 구간 = VideoSegment 하나.
      - source_timerange: 원본 영상에서 잘라올 위치
      - target_timerange: 타임라인 상 배치 위치(앞 구간 바로 뒤, 무음만큼 당겨짐)
    영상 세그먼트가 오디오를 함께 들고 있어 음성도 같은 컷으로 동기된다.

    captions: [{start, dur, text}] (컷 타임라인 기준). 주어지면 텍스트 트랙에 자막 추가.

    returns: (저장된 드래프트 폴더 경로, 컷 후 총 길이 초)
    """
    folder = cc.DraftFolder(capcut_draft_dir())
    script = folder.create_draft(draft_name, width, height, fps=fps, allow_replace=True)
    script.add_track(cc.TrackType.video)
    if captions:
        script.add_track(cc.TrackType.text)

    # 샌드박스 함정(pycapcut-mac 스킬): CapCut은 ~/WebstormProjects 같은 외부 경로의
    # 미디어를 읽지 못한다("파일에 액세스할 수 없음"). 드래프트 폴더 안(~/Movies/CapCut/…)
    # 으로 복사하고 그 경로를 소재로 써야 한다.
    draft_path = f"{capcut_draft_dir()}/{draft_name}"
    materials_dir = os.path.join(draft_path, "materials")
    os.makedirs(materials_dir, exist_ok=True)
    local_media = os.path.join(materials_dir, os.path.basename(video_path))
    shutil.copyfile(video_path, local_media)

    # 소재는 한 번만 생성해 재사용 (같은 파일을 여러 세그먼트가 참조)
    material = cc.VideoMaterial(local_media)

    timeline = 0.0  # 타임라인 커서(초)
    for k in keeps:
        seg = cc.VideoSegment(
            material,
            target_timerange=trange(us(timeline), us(k.dur)),
            source_timerange=trange(us(k.start), us(k.dur)),
        )
        script.add_segment(seg)
        timeline += k.dur

    # 자막
    if captions:
        for c in captions:
            _add_caption(script, c["text"], c["start"], c["dur"])

    script.save()  # ★ 저장 성공 ≠ 검증. 캡컷에서 직접 재생해야 검증 완료.

    # pycapcut는 draft_content.json(6.7 win 스키마)을 쓰지만 CapCut 8.7(mac)은
    # draft_info.json을 읽는다 → 설치 버전이 열 수 있게 변환 (capcut_compat 참조)
    make_capcut_openable(draft_path, us(timeline))
    # CapCut 8.7은 root_meta_info.json에 등록된 드래프트만 유지 (미등록 폴더는 휴지통行)
    register_in_root_meta(draft_path, us(timeline))
    return draft_path, timeline


def _add_caption(script, text: str, start: float, dur: float) -> None:
    """텍스트 트랙에 자막 1개. 하단(CAPTION_Y) 가운데, 얇은 반투명 외곽선(브이로그 톤)."""
    ts = cc.TextSegment(
        text,
        trange(us(start), us(dur)),
        style=cc.TextStyle(size=CAPTION_SIZE, color=(1.0, 1.0, 1.0), align=1),
        clip_settings=cc.ClipSettings(transform_y=CAPTION_Y),
        border=cc.TextBorder(color=(0.0, 0.0, 0.0),
                             width=CAPTION_BORDER_WIDTH, alpha=CAPTION_BORDER_ALPHA),
    )
    script.add_segment(ts)


def build_merged_draft(items: list[dict], draft_name: str,
                       width: int = 1920, height: int = 1080, fps: int = 30
                       ) -> tuple[str, float]:
    """여러 영상을 하나의 드래프트로 이어붙인다 (브이로그 합치기).

    items: [{path, keeps, captions}] — 순서대로 타임라인에 연결.
      각 영상의 내부 점프컷(keeps)은 유지되고, 클립들은 하드컷으로 이어진다.
      자막(클립별 0기준 컷타임라인)은 그 클립이 시작하는 위치만큼 밀어 배치한다.

    returns: (드래프트 경로, 총 길이 초)
    """
    folder = cc.DraftFolder(capcut_draft_dir())
    script = folder.create_draft(draft_name, width, height, fps=fps, allow_replace=True)
    script.add_track(cc.TrackType.video)
    if any(it.get("captions") for it in items):
        script.add_track(cc.TrackType.text)

    draft_path = f"{capcut_draft_dir()}/{draft_name}"
    materials_dir = os.path.join(draft_path, "materials")
    os.makedirs(materials_dir, exist_ok=True)

    timeline = 0.0
    used_names: set[str] = set()
    for it in items:
        src = it["path"]
        # 같은 basename 충돌 방지(여러 폴더의 GX0001 등) → 고유 파일명으로 복사
        base = os.path.basename(src)
        stem, ext = os.path.splitext(base)
        local_name, i = base, 2
        while local_name in used_names:
            local_name = f"{stem}_{i}{ext}"
            i += 1
        used_names.add(local_name)
        local_media = os.path.join(materials_dir, local_name)
        shutil.copyfile(src, local_media)
        material = cc.VideoMaterial(local_media)

        clip_offset = timeline  # 이 클립이 합본 타임라인에서 시작하는 위치
        for k in it["keeps"]:
            script.add_segment(cc.VideoSegment(
                material,
                target_timerange=trange(us(timeline), us(k.dur)),
                source_timerange=trange(us(k.start), us(k.dur)),
            ))
            timeline += k.dur
        for c in (it.get("captions") or []):
            _add_caption(script, c["text"], clip_offset + c["start"], c["dur"])

    script.save()
    make_capcut_openable(draft_path, us(timeline))
    register_in_root_meta(draft_path, us(timeline))
    return draft_path, timeline
