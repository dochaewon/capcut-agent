#!/usr/bin/env python
"""여러 영상을 하나의 브이로그 드래프트로 합치기.

사용:
  python merge.py <폴더> --name 여행브이로그
  python merge.py a.mp4 b.mp4 c.mp4 --name vlog
  옵션: --noise --silence --pad --no-subs --no-filler --recursive

각 영상은 무음·잔말·NG 컷 + 자막 후, 순서대로(파일명 정렬) 한 타임라인에 이어붙는다.
★ 순차 분석(ASR 직렬) + 빌드 중 CapCut 자동 종료(인덱스 충돌 방지).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from app.config import assert_macos_arm
from app.draft import build_merged_draft
from app.pipeline import analyze

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv")


def collect(inputs: list[str], recursive: bool) -> list[str]:
    vids: list[str] = []
    for inp in inputs:
        if os.path.isdir(inp):
            if recursive:
                for root, _, files in os.walk(inp):
                    vids += [os.path.join(root, f) for f in files
                             if f.lower().endswith(VIDEO_EXT) and not f.startswith(".")]
            else:
                vids += [os.path.join(inp, f) for f in os.listdir(inp)
                         if f.lower().endswith(VIDEO_EXT) and not f.startswith(".")]
        elif os.path.isfile(inp) and inp.lower().endswith(VIDEO_EXT):
            vids.append(inp)
    return sorted(vids)


def main() -> int:
    ap = argparse.ArgumentParser(description="여러 영상 → 하나의 브이로그 드래프트")
    ap.add_argument("inputs", nargs="+", help="폴더 또는 영상 파일들 (순서=파일명 정렬)")
    ap.add_argument("--name", required=True, help="합본 드래프트 이름")
    ap.add_argument("--noise", type=float, default=None)
    ap.add_argument("--silence", type=float, default=0.5)
    ap.add_argument("--pad", type=float, default=0.10)
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--no-filler", action="store_true")
    ap.add_argument("--recursive", action="store_true")
    args = ap.parse_args()

    assert_macos_arm()
    videos = collect(args.inputs, args.recursive)
    if len(videos) < 1:
        print("[error] 합칠 영상이 없습니다.")
        return 1

    if subprocess.run(["pgrep", "-x", "CapCut"], capture_output=True).returncode == 0:
        print("⚠ CapCut 실행 중 → 종료합니다. (끝나면 다시 여세요)")
        subprocess.run(["killall", "CapCut"], capture_output=True)
        time.sleep(1.5)

    print(f"▶ {len(videos)}개 영상 분석 → 합치기\n")
    t0 = time.time()
    items = []
    for i, v in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {os.path.basename(v)}")
        try:
            keeps, caps, total = analyze(
                v, noise=args.noise, silence=args.silence, pad=args.pad,
                subs=not args.no_subs, filler=not args.no_filler)
            kept = sum(k.dur for k in keeps)
            items.append({"path": v, "keeps": keeps, "captions": caps})
            print(f"    {total:.0f}s → {kept:.0f}s, 자막 {len(caps) if caps else 0}")
        except Exception as e:  # noqa: BLE001
            print(f"    ✗ 건너뜀: {type(e).__name__}: {e}")

    if not items:
        print("[error] 분석 성공한 영상이 없습니다.")
        return 2

    print("\n▶ 합본 드래프트 빌드 …")
    path, out_len = build_merged_draft(items, args.name)
    print(f"  저장: {path}")
    print(f"  합본 길이: {out_len:.0f}s ({len(items)}개 클립)  (총 {time.time() - t0:.0f}s)")
    print("\nCapCut을 열어 합본을 재생해 클립 연결·자막을 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
