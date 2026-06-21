"""환경/경로 해석. 캡컷 드래프트 폴더는 pycapcut-mac 스킬 참조 — 샌드박스 경로."""
from __future__ import annotations

import os
import platform

# CapCut(글로벌)과 剪映(중국판)의 Mac 드래프트 경로.
# 이 폴더는 CapCut을 최소 1회 실행해야 생성된다 (pycapcut-mac 스킬 참조).
_CANDIDATES = [
    "~/Movies/CapCut/User Data/Projects/com.lveditor.draft",
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
]


def capcut_draft_dir() -> str:
    """존재하는 캡컷 드래프트 폴더 경로를 돌려준다. 없으면 친절한 에러."""
    for c in _CANDIDATES:
        p = os.path.expanduser(c)
        if os.path.isdir(p):
            return p
    raise FileNotFoundError(
        "캡컷 드래프트 폴더를 찾지 못했습니다. CapCut을 1회 실행해 빈 프로젝트를 "
        "만들고 닫으면 다음 경로가 생성됩니다:\n  "
        + os.path.expanduser(_CANDIDATES[0])
    )


def assert_macos_arm() -> None:
    sysname, machine = platform.system(), platform.machine()
    if sysname != "Darwin":
        # 트랙 A 전용 코드는 아니지만, 경로 가정이 Mac 기준이라 경고만.
        print(f"[warn] 이 도구는 macOS 기준입니다 (현재: {sysname} {machine}).")
