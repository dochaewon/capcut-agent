#!/usr/bin/env python
"""1단 CLI: 무음 컷 점프컷 드래프트 생성 (UI 없음).

사용:
  python cut.py <video.mp4> [--name 드래프트이름] [--noise -30] [--silence 0.5] [--pad 0.1]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from app.config import assert_macos_arm
from app.draft import build_jumpcut_draft
from app.silence import keep_segments


def main() -> int:
    ap = argparse.ArgumentParser(description="무음 컷 → 캡컷 점프컷 드래프트 (1단)")
    ap.add_argument("video", help="입력 mp4/mov 경로")
    ap.add_argument("--name", default=None, help="드래프트 이름 (기본: 파일명_cut)")
    ap.add_argument("--noise", type=float, default=None,
                    help="무음 임계 dB (생략 시 음량 분포에서 자동 산출)")
    ap.add_argument("--silence", type=float, default=0.5, help="최소 무음 길이 초 (기본 0.5)")
    ap.add_argument("--pad", type=float, default=0.10, help="발화 구간 양끝 여유 초 (기본 0.1)")
    ap.add_argument("--no-subs", action="store_true", help="자막(ASR) 생략, 무음컷만")
    ap.add_argument("--no-filler", action="store_true", help="잔말·NG 컷 생략")
    args = ap.parse_args()

    assert_macos_arm()
    if not os.path.isfile(args.video):
        print(f"[error] 파일 없음: {args.video}")
        return 1

    name = args.name or (os.path.splitext(os.path.basename(args.video))[0] + "_cut")

    t0 = time.time()
    noise_label = f"{args.noise}dB" if args.noise is not None else "auto"
    print(f"▶ silencedetect (noise={noise_label}, d={args.silence}s, pad={args.pad}s) …")
    keeps, total, used_noise = keep_segments(
        args.video, noise_db=args.noise, min_silence=args.silence, pad=args.pad
    )
    if args.noise is None:
        print(f"  자동 임계값: {used_noise}dB")
    kept = sum(k.dur for k in keeps)
    print(f"  원본 {total:7.2f}s → 보존 {kept:7.2f}s "
          f"({len(keeps)}개 조각, {(1 - kept / total) * 100:4.1f}% 컷)")

    caps = None
    if not args.no_subs:
        print("▶ asr (mlx-whisper, 전체 대본 추출) …")
        from app.asr import transcribe_sync
        from app.captions import make_captions
        from app.filler import remove_spans, subtract
        segs = transcribe_sync(args.video)
        print(f"  대본 {len(segs)}세그먼트")

        if not args.no_filler:
            print("▶ filler (잔말·NG 컷) …")
            removals = remove_spans(segs)
            before = sum(k.dur for k in keeps)
            keeps = subtract(keeps, removals)
            after = sum(k.dur for k in keeps)
            print(f"  잔말·NG {len(removals)}구간 → 추가 {before - after:.1f}s 컷, "
                  f"남은 {len(keeps)}조각")

        caps = make_captions(segs, keeps)
        print(f"  자막 {len(caps)}컷")

    print("▶ build_draft …")
    path, out_len = build_jumpcut_draft(args.video, keeps, name, caps)
    print(f"  드래프트 저장: {path}")
    print(f"  컷 후 길이: {out_len:.2f}s   (소요 {time.time() - t0:.1f}s)")
    print()
    print("✓ 빌드 완료 — 단, 검증은 아직입니다.")
    print("  CapCut을 열어 위 드래프트를 재생해 점프컷이 자연스러운지 직접 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
