# 🎬 캡컷 에이전트 (CapCut Agent)

> 한국어 토킹 영상을 넣으면 **무음·잔말·NG 컷 + 자막**이 된 CapCut 드래프트를 자동으로 만들어 주는 로컬 웹 도구.

말하는 영상(mp4/mov)을 올리면 → 무음 구간을 잘라 **점프컷**하고 → mlx-whisper로 **대본을 전사**해 **자막**을 깔고 → 잔말("음/어")과 더듬어 다시 한 **NG 테이크**를 걷어낸 뒤 → **CapCut에서 바로 열리는 드래프트**로 저장합니다. 결과물은 완성 영상이 아니라 *편집 가능한 드래프트* — AI가 대부분을 깎아두면 사람이 마지막 손질만 하면 됩니다.

![platform](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-black)
![python](https://img.shields.io/badge/python-3.11-blue)
![license](https://img.shields.io/badge/license-MIT-green)

---

## ✨ 주요 기능

| 기능 | 설명 |
|---|---|
| **무음 컷** | ffmpeg `silencedetect` + 영상 음량 분포 기반 **적응형 임계값**(잡음 많은 GoPro도 OK) |
| **자막** | mlx-whisper(Apple Silicon)로 전사 → **의존명사 청크**로 자연스러운 줄바꿈, 브이로그 톤 |
| **잔말·NG 컷** | 비어휘적 추임새(음/어/흠) 단어 단위 제거 + 인접 중복(다시 말한 테이크) 제거 |
| **여러 클립 합치기** | 여러 영상을 하나의 브이로그 드래프트로 이어붙이기 (자막 타임라인 자동 정렬) |
| **배치 처리** | 폴더째 / 웹 멀티 업로드 → 순차 자동 처리 (파일명 충돌 자동 회피) |
| **로컬 웹 UI** | drag & drop + SSE 실시간 단계 표시 (FastAPI + 정적 HTML 1장) |

런타임 파이프라인: **`silence → asr → filler → draft+자막`**

---

## 🧩 기술적 도전 — CapCut 8.7 드래프트 포맷 리버스 엔지니어링

핵심 난이도는 영상 처리가 아니라 **CapCut의 비공개 드래프트 포맷에 맞춰 파일을 생성하는 것**이었습니다. 라이브러리(`pycapcut`)가 만든 드래프트가 최신 CapCut에서 열리지 않는 문제를, 실제 드래프트와 diff하며 해결했습니다:

- **`draft_content.json` → `draft_info.json`** — pycapcut는 구버전(6.7/Windows) 스키마를 쓰지만 CapCut 8.7(Mac)은 `draft_info.json`만 읽음. 버전 메타·플랫폼 교체 후 파일명 변환.
- **`root_meta_info.json` 마스터 인덱스** — 등록 안 된 드래프트는 실행 시 **휴지통으로 이동**. 인덱스 항목을 직접 주입해 해결.
- **고유 ID / 빈 이름 함정** — pycapcut가 모든 드래프트에 같은 draft_id·빈 draft_name을 박아 충돌 → UUID 재생성 + 폴더명 부여.
- **마이크로초 단위** — 모든 시간이 µs 정수, `trange(start, duration)`의 2번째 인자는 duration(끝시간 아님).
- **샌드박스** — CapCut은 외부 경로 미디어를 못 읽음 → 소재를 드래프트 폴더 내부로 복사.
- **ASR 직렬화** — whisper/numba 동시 호출 시 segfault → `asyncio.Lock` 직렬화 + content-hash 캐시.

> 설치된 CapCut 버전이 달라도 `ensure_template()`이 사용자의 실제 드래프트에서 호환 값을 자동 추출하도록 설계.

---

## 🚀 설치 (macOS · Apple Silicon)

```bash
# 사전 요구: Homebrew, CapCut 데스크톱 앱(1회 실행해 드래프트 폴더 생성)
brew install python@3.11 ffmpeg libmediainfo

git clone https://github.com/dochaewon/capcut-agent.git
cd capcut-agent
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

> **Apple Silicon Mac** 기준입니다. Mac에서는 드래프트 생성·재생까지 되고, **MP4 내보내기는 Windows CapCut에서만** 됩니다(CapCut의 제약).

---

## 📖 사용법

### 웹 UI (권장)
```bash
python -m uvicorn app.server:app --port 8765
# 브라우저에서 http://127.0.0.1:8765 → 영상 1개 또는 여러 개 드래그
```
> 처리 중에는 **CapCut을 닫아두세요** (드래프트 인덱스 충돌 방지).

### CLI
```bash
python cut.py 영상.mp4                          # 한 영상 → 점프컷+자막 드래프트
python cut.py 영상.mp4 --no-subs                # 무음컷만
python batch.py ~/영상폴더 --skip-existing      # 폴더째 일괄
python merge.py ~/여행폴더 --name 여행브이로그   # 여러 영상 → 하나의 브이로그
```

생성된 드래프트는 CapCut 홈의 **프로젝트 목록**에 나타납니다 (가져오기 아님 — 더블클릭해 열기).

---

## 🗂 프로젝트 구조

```
app/
  server.py         FastAPI + SSE 스테퍼
  static/index.html 단일 페이지 UI (drag&drop, 멀티 업로드 큐)
  silence.py        무음 감지 + 적응형 임계값
  asr.py            mlx-whisper 전사 (ASR_LOCK, content-hash 캐시)
  captions.py       시간 매핑 + 의존명사 청크
  filler.py         잔말·NG 컷
  draft.py          CapCut 드래프트 빌드 (점프컷 / 합치기)
  capcut_compat.py  CapCut 8.7 호환 변환 + 인덱스 등록  ← 핵심
  pipeline.py       분석 파이프라인 (재사용 단위)
cut.py / batch.py / merge.py   CLI 진입점
```

---

## ⚠️ 면책

본 프로젝트는 **CapCut / ByteDance와 무관한** 비공식 도구입니다. CapCut의 드래프트 파일 형식과 상호운용하기 위한 것으로, CapCut의 코드를 포함하지 않습니다. 사용 시 CapCut 이용약관을 준수하세요. 드래프트 포맷은 CapCut 업데이트로 바뀔 수 있습니다(본 코드는 **8.7.0 / macOS** 기준 검증).

## 📄 라이선스

[MIT](./LICENSE) © dochaewon (winnie)

자유롭게 사용·수정·배포할 수 있으나 **저작권 및 라이선스 고지를 반드시 포함**해야 합니다.

---

made with care by **dochaewon (winnie)**
