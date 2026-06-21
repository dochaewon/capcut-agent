#!/usr/bin/env python
"""배치 처리: 폴더 안 모든 영상을 순차로 점프컷+자막 드래프트로 만든다.

사용:
  python batch.py <폴더> [--noise -20] [--silence 0.5] [--pad 0.1]
                  [--no-subs] [--no-filler] [--recursive] [--skip-existing]

★ 순차 처리 이유 (pycapcut-mac 스킬):
  - ASR은 ASR_LOCK으로 직렬 (numba 동시호출 segfault)
  - 빌드 중 CapCut이 열려 있으면 종료 시 인덱스를 덮어써 등록이 날아감
    → 시작 시 CapCut을 자동 종료한다. 끝나면 CapCut 열면 목록에 쫙 뜬다.
  - 영상마다 드래프트 폴더로 복사(무거움) → 디스크 여유 확인
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from app.config import assert_macos_arm, capcut_draft_dir
from app.draft import build_jumpcut_draft
from app.silence import keep_segments

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv")


def find_videos(folder: str, recursive: bool) -> list[str]:
    vids: list[str] = []
    if recursive:
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(VIDEO_EXT) and not f.startswith("."):
                    vids.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and f.lower().endswith(VIDEO_EXT) and not f.startswith("."):
                vids.append(p)
    return sorted(vids)


def resolve_names(videos: list[str]) -> dict[str, str]:
    """경로 → 고유 드래프트명. 같은 파일명(카메라 GX0001 등) 충돌 시 상위폴더명/번호로 구분.

    안 그러면 다른 영상인데 이름이 같아 서로 덮어쓴다("섞임").
    """
    names: dict[str, str] = {}
    used: set[str] = set()
    for path in videos:
        stem = os.path.splitext(os.path.basename(path))[0]
        cand = f"{stem}_cut"
        if cand in used:  # 충돌 → 상위 폴더명 붙이기
            parent = os.path.basename(os.path.dirname(path))
            cand = f"{parent}_{stem}_cut"
        n = cand
        i = 2
        while n in used:  # 그래도 충돌 → 번호
            n = f"{cand}_{i}"
            i += 1
        used.add(n)
        names[path] = n
    return names


def process_one(path: str, name: str, args) -> tuple[str, str, float, float, int]:
    """returns (status, draft_name, total_s, out_len_s, captions)"""
    if args.skip_existing and os.path.isdir(os.path.join(capcut_draft_dir(), name)):
        return ("skip", name, 0.0, 0.0, 0)

    keeps, total, _ = keep_segments(path, noise_db=args.noise,
                                    min_silence=args.silence, pad=args.pad)
    caps = None
    if not args.no_subs:
        from app.asr import transcribe_sync
        from app.captions import make_captions
        from app.filler import remove_spans, subtract
        segs = transcribe_sync(path)
        if not args.no_filler:
            keeps = subtract(keeps, remove_spans(segs))
        caps = make_captions(segs, keeps)

    _, out_len = build_jumpcut_draft(path, keeps, name, caps)
    return ("ok", name, total, out_len, len(caps) if caps else 0)


def main() -> int:
    ap = argparse.ArgumentParser(description="폴더 배치 → 캡컷 드래프트 일괄 생성")
    ap.add_argument("folder", help="영상이 든 폴더")
    ap.add_argument("--noise", type=float, default=None, help="무음 임계 dB (생략=자동)")
    ap.add_argument("--silence", type=float, default=0.5)
    ap.add_argument("--pad", type=float, default=0.10)
    ap.add_argument("--no-subs", action="store_true", help="자막 생략")
    ap.add_argument("--no-filler", action="store_true", help="잔말·NG 컷 생략")
    ap.add_argument("--recursive", action="store_true", help="하위 폴더까지")
    ap.add_argument("--skip-existing", action="store_true", help="이미 만든 드래프트 건너뛰기")
    args = ap.parse_args()

    assert_macos_arm()
    if not os.path.isdir(args.folder):
        print(f"[error] 폴더 없음: {args.folder}")
        return 1

    videos = find_videos(args.folder, args.recursive)
    if not videos:
        print(f"[info] 영상 없음 ({', '.join(VIDEO_EXT)})")
        return 0

    # CapCut이 열려 있으면 인덱스 충돌 → 자동 종료
    if subprocess.run(["pgrep", "-x", "CapCut"], capture_output=True).returncode == 0:
        print("⚠ CapCut 실행 중 → 인덱스 충돌 방지 위해 종료합니다. (끝나면 다시 여세요)")
        subprocess.run(["killall", "CapCut"], capture_output=True)
        time.sleep(1.5)

    names = resolve_names(videos)  # 파일명 충돌 방지(다른 영상 덮어쓰기 방지)
    print(f"▶ 영상 {len(videos)}개 배치 시작\n")
    t0 = time.time()
    ok = skipped = failed = 0
    for i, v in enumerate(videos, 1):
        base = os.path.basename(v)
        print(f"[{i}/{len(videos)}] {base}")
        try:
            t = time.time()
            status, name, total, out_len, ncap = process_one(v, names[v], args)
            if status == "skip":
                print(f"    ⤳ 건너뜀 (이미 있음: {name})")
                skipped += 1
            else:
                cut_pct = (1 - out_len / total) * 100 if total else 0
                print(f"    ✓ {name}  {total:.0f}s→{out_len:.0f}s ({cut_pct:.0f}% 컷, "
                      f"자막 {ncap})  {time.time() - t:.0f}s")
                ok += 1
        except Exception as e:  # noqa: BLE001 — 한 영상 실패가 배치를 멈추지 않게
            print(f"    ✗ 실패: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n완료: 성공 {ok} · 건너뜀 {skipped} · 실패 {failed}  "
          f"(총 {time.time() - t0:.0f}s)")
    print("CapCut을 열면 프로젝트 목록에 모두 나타납니다. 각 드래프트를 재생해 검증하세요.")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
