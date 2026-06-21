"""2단: 로컬 웹 (FastAPI + 정적 HTML 1장).

drag/drop으로 영상을 올리면 SSE로 단계별 진행을 흘려보내며 점프컷 드래프트를 만든다.
런타임 단계(스펙): silence → asr → filler → draft+자막.
2단 현재 구현 단계는 silence → draft. (asr/filler는 3·4단에서 합류)

주의:
- ASR은 asyncio.Lock으로 직렬화한다 (numba 비안전, 동시 호출 시 segfault). 3단에서 사용.
- 단계당 최소 0.5s 지연을 강제해 캐시 hit 시에도 스테퍼 애니메이션이 보이게 한다.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

from fastapi import FastAPI, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .asr import transcribe
from .captions import make_captions
from .draft import build_jumpcut_draft
from .filler import remove_spans, subtract
from .silence import keep_segments

_HERE = os.path.dirname(__file__)
_STATIC = os.path.join(_HERE, "static")
_UPLOADS = os.path.join(os.path.dirname(_HERE), "uploads")
os.makedirs(_UPLOADS, exist_ok=True)

# ASR 직렬화 락은 app/asr.py 의 ASR_LOCK 이 담당 (transcribe()가 감싼다).
STAGE_MIN_SECONDS = 0.5  # 단계당 최소 지연

app = FastAPI(title="캡컷 에이전트")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    with open(os.path.join(_STATIC, "index.html"), encoding="utf-8") as f:
        return f.read()


@app.post("/upload")
async def upload(file: UploadFile):
    """영상 업로드 → uploads/에 저장, 처리용 id 반환."""
    job_id = uuid.uuid4().hex[:12]
    safe_name = os.path.basename(file.filename or "video.mp4")
    job_dir = os.path.join(_UPLOADS, job_id)  # job별 하위폴더 → 원본 파일명 보존
    os.makedirs(job_dir, exist_ok=True)
    dest = os.path.join(job_dir, safe_name)
    with open(dest, "wb") as out:
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    return {"id": job_id, "name": safe_name}


def _find_upload(job_id: str) -> str | None:
    job_dir = os.path.join(_UPLOADS, job_id)
    if os.path.isdir(job_dir):
        files = os.listdir(job_dir)
        if files:
            return os.path.join(job_dir, files[0])
    return None


@app.get("/run/{job_id}")
async def run(job_id: str, noise: float | None = None,
              silence: float = 0.5, pad: float = 0.1, name: str | None = None):
    """SSE: silence → asr → filler → draft 단계를 흘려보낸다.

    name: 드래프트 이름(확장자/_cut 제외 기준). 멀티 업로드 시 프론트가 파일명 충돌을
          미리 풀어 넘긴다(다른 영상 덮어쓰기 방지). 없으면 파일명에서 유도.
    """
    path = _find_upload(job_id)

    async def gen():
        if not path or not os.path.isfile(path):
            yield _sse("error", {"message": "업로드 파일을 찾지 못했습니다."})
            return

        base = name or os.path.splitext(os.path.basename(path))[0]
        draft_name = f"{base}_cut"
        # 런타임 단계: silence → asr → filler → draft+자막
        yield _sse("stages", {"stages": ["silence", "asr", "filler", "draft"]})

        try:
            # ── silence ──────────────────────────────────────────────
            yield _sse("stage", {"name": "silence", "status": "running"})
            t = asyncio.get_event_loop().time()
            keeps, total, used_noise = await asyncio.to_thread(
                keep_segments, path, noise, silence, pad)
            kept = sum(k.dur for k in keeps)
            await _floor(t)
            yield _sse("stage", {"name": "silence", "status": "done", "stats": {
                "원본": f"{total:.1f}s", "보존": f"{kept:.1f}s",
                "컷": f"{(1 - kept / total) * 100:.1f}%",
                "조각": str(len(keeps)), "임계값": f"{used_noise}dB",
            }})

            # ── asr (전체 대본 추출, ASR_LOCK 직렬화) ──────────────────
            yield _sse("stage", {"name": "asr", "status": "running"})
            t = asyncio.get_event_loop().time()
            segs = await transcribe(path)
            chars = sum(len(s["text"]) for s in segs)
            await _floor(t)
            yield _sse("stage", {"name": "asr", "status": "done", "stats": {
                "대본 세그먼트": str(len(segs)), "글자수": str(chars),
            }})

            # ── filler (잔말·NG 컷, 대본 기반) ─────────────────────────
            yield _sse("stage", {"name": "filler", "status": "running"})
            t = asyncio.get_event_loop().time()
            removals = remove_spans(segs)
            final_keeps = subtract(keeps, removals)
            final_kept = sum(k.dur for k in final_keeps)
            removed_s = kept - final_kept
            caps = make_captions(segs, final_keeps)
            await _floor(t)
            yield _sse("stage", {"name": "filler", "status": "done", "stats": {
                "잔말·NG 구간": str(len(removals)), "추가 컷": f"{removed_s:.1f}s",
                "남은 조각": str(len(final_keeps)),
            }})

            # ── draft (점프컷 + 자막) ─────────────────────────────────
            yield _sse("stage", {"name": "draft", "status": "running"})
            t = asyncio.get_event_loop().time()
            draft_path, out_len = await asyncio.to_thread(
                build_jumpcut_draft, path, final_keeps, draft_name, caps)
            await _floor(t)
            yield _sse("stage", {"name": "draft", "status": "done", "stats": {
                "결과 길이": f"{out_len:.1f}s", "자막": str(len(caps)),
                "드래프트": draft_name,
            }})

            yield _sse("result", {
                "draft_name": draft_name, "draft_path": draft_path,
                "total": round(total, 1), "kept": round(final_kept, 1),
                "cut_pct": round((1 - final_kept / total) * 100, 1),
                "segments": len(final_keeps), "noise": used_noise,
                "out_len": round(out_len, 1), "captions": len(caps),
            })
        except Exception as e:  # noqa: BLE001 — 사용자에게 그대로 전달
            yield _sse("error", {"message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _floor(start_t: float) -> None:
    """단계 시작 후 최소 STAGE_MIN_SECONDS가 지나도록 보정 지연."""
    elapsed = asyncio.get_event_loop().time() - start_t
    if elapsed < STAGE_MIN_SECONDS:
        await asyncio.sleep(STAGE_MIN_SECONDS - elapsed)


if os.path.isdir(_STATIC):
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
