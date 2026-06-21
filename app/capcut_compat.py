"""pycapcut 출력(구 draft_content.json)을 설치된 CapCut 버전이 여는 형태로 변환.

★ pycapcut-mac 스킬의 'draft_info.json' 함정의 실체 ★
pycapcut 0.0.3은 타임라인을 `draft_content.json`(app_version 6.7.0 / windows 스키마)으로 쓴다.
그러나 CapCut 8.7(Mac)은 타임라인을 **`draft_info.json`**에서 읽는다 — draft_content.json은
읽지도 않는다. 그래서 드래프트가 갤러리엔 뜨지만 더블클릭해도 안 열린다.

해결: pycapcut 저장 직후 이 패처를 돌려
  1) draft_content.json 의 버전/플랫폼 메타를 설치 버전(8.7 mac)으로 교체
  2) 8.7에만 있는 상위 키 4개 주입
  3) 결과를 draft_info.json 으로 기록 (CapCut이 실제로 읽는 파일)
  4) draft_meta_info.json 의 tm_duration(갤러리 길이) 채움
  5) CapCut이 파싱에 필요한 보조파일/빈폴더 스캐폴딩 (이게 없으면 갤러리엔 떠도
     타임라인을 못 읽어 00:00 빈 프로젝트로 취급하고 열리지 않는다)

설치 버전이 바뀌면 capcut_template.json 만 다시 추출하면 된다 (refresh_template 참조).
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid


def _uuid() -> str:
    """CapCut 형식 대문자 UUID."""
    return str(uuid.uuid4()).upper()

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "capcut_template.json")
_SCAFFOLD_DIR = os.path.join(os.path.dirname(__file__), "capcut_scaffold")

# CapCut이 직접 만든 빈 프로젝트(0617)와 diff해 확인한, 드래프트가 '열리기 위해'
# 필요한 최소 보조 구성. draft.extra / draft_cover.jpg / *.bak / *.tmp 는 없어도
# CapCut이 첫 오픈 시 재생성하므로 만들지 않는다.
_SCAFFOLD_FILES = (
    "draft_agency_config.json",
    "draft_biz_config.json",
    "performance_opt_info.json",
    "attachment_editing.json",
)
_SCAFFOLD_DIRS = (
    "Resources", "adjust_mask", "common_attachment",
    "matting", "qr_upload", "smart_crop",
)


def ensure_template() -> None:
    """capcut_template.json이 없으면 설치된 CapCut의 실제 드래프트에서 자동 생성한다.

    기기 식별자가 들어가므로 이 파일은 깃에 올리지 않는다(.gitignore). 대신 각자
    환경에서 처음 빌드할 때 자기 CapCut 드래프트를 보고 만든다.
    """
    if os.path.isfile(_TEMPLATE_PATH):
        return
    from .config import capcut_draft_dir
    root = capcut_draft_dir()
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if os.path.isfile(os.path.join(d, "draft_info.json")):
            refresh_template(d)
            return
    raise FileNotFoundError(
        "capcut_template.json이 없고 참조할 CapCut 드래프트도 없습니다.\n"
        "CapCut에서 빈 프로젝트를 1개 만들어 저장(타임라인에 클립 하나 올리기)한 뒤 "
        "다시 실행하세요. 그러면 자동 생성됩니다."
    )


def _load_template() -> dict:
    ensure_template()
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def make_capcut_openable(draft_folder: str, duration_us: int) -> None:
    """draft_folder 안의 pycapcut 산출물을 설치된 CapCut이 열 수 있게 변환한다."""
    tmpl = _load_template()
    content_path = os.path.join(draft_folder, "draft_content.json")
    info_path = os.path.join(draft_folder, "draft_info.json")
    meta_path = os.path.join(draft_folder, "draft_meta_info.json")

    with open(content_path, encoding="utf-8") as f:
        doc = json.load(f)

    # 1) 버전/플랫폼 메타를 설치 버전 실제값으로 교체
    doc["new_version"] = tmpl["new_version"]
    doc["platform"] = tmpl["platform"]
    doc["last_modified_platform"] = tmpl["last_modified_platform"]
    # 2) 설치 버전에만 있는 상위 키 주입 (없으면 8.7이 파싱 중 빠진 필드로 취급)
    for k, v in tmpl["extra_keys"].items():
        doc.setdefault(k, v)

    # 2.5) pycapcut는 draft_info.id 를 고정값으로 박는다 → 드래프트마다 고유 id 부여
    #      (안 그러면 여러 드래프트가 같은 id로 충돌)
    doc["id"] = _uuid()

    # 3) CapCut이 실제로 읽는 파일로 기록
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    # 구 파일은 혼동 방지를 위해 제거 (CapCut 8.7은 무시함)
    os.remove(content_path)

    # 4) draft_meta_info 보정: pycapcut는 draft_name="" + 고정 draft_id 를 쓴다.
    #    갤러리 이름과 인덱스 정합을 위해 폴더명·고유 id·길이를 채운다.
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta["draft_name"] = os.path.basename(draft_folder.rstrip("/"))
    meta["draft_id"] = _uuid()
    meta["draft_fold_path"] = draft_folder
    meta["tm_duration"] = int(duration_us)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    # 5) 보조파일/빈폴더 스캐폴딩
    for name in _SCAFFOLD_FILES:
        shutil.copyfile(os.path.join(_SCAFFOLD_DIR, name),
                        os.path.join(draft_folder, name))
    for d in _SCAFFOLD_DIRS:
        os.makedirs(os.path.join(draft_folder, d), exist_ok=True)

    draft_id = doc["id"]
    # 타임라인 레이아웃: 도크에 우리 드래프트의 타임라인 1개를 등록
    layout = {"dockItems": [{"dockIndex": 0, "ratio": 1,
                             "timelineIds": [draft_id], "timelineNames": [draft_id]}],
              "layoutOrientation": 1}
    with open(os.path.join(draft_folder, "timeline_layout.json"), "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False)
    # 가상 스토어: 서브드래프트 없음 → 빈 구조
    vstore = {"draft_materials": [], "draft_virtual_store": [
        {"type": 0, "value": [{"creation_time": 0, "display_name": "", "filter_type": 0,
                               "id": "", "import_time": 0, "import_time_us": 0,
                               "sort_sub_type": 0, "sort_type": 0, "subdraft_filter_type": 0}]},
        {"type": 1, "value": []}, {"type": 2, "value": []}]}
    with open(os.path.join(draft_folder, "draft_virtual_store.json"), "w", encoding="utf-8") as f:
        json.dump(vstore, f, ensure_ascii=False)


def register_in_root_meta(draft_folder: str, duration_us: int) -> None:
    """드래프트를 com.lveditor.draft/root_meta_info.json 마스터 인덱스에 등록한다.

    ★ pycapcut-mac 스킬: CapCut 8.7은 root_meta_info.json 에 등록된 드래프트만 유효로
    보고, 등록 안 된 폴더는 실행 시 .recycle_bin 으로 옮긴다. draft_info.json + 보조파일이
    완벽해도 이 인덱스에 없으면 갤러리에 잠깐 떴다 사라진다.

    주의: CapCut이 실행 중이면 종료 시 인덱스를 덮어써 우리 항목이 날아갈 수 있다.
    빌드 중에는 CapCut을 닫아두고, 빌드 후 열 것.
    """
    root = os.path.dirname(draft_folder.rstrip("/"))  # com.lveditor.draft
    rmi_path = os.path.join(root, "root_meta_info.json")
    with open(os.path.join(draft_folder, "draft_meta_info.json"), encoding="utf-8") as f:
        meta = json.load(f)
    draft_id = meta["draft_id"]
    now_us = time.time_ns() // 1000

    entry = {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False, "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "", "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": os.path.join(draft_folder, "draft_cover.jpg"),
        "draft_fold_path": draft_folder,
        "draft_id": draft_id,
        "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
        "draft_is_invisible": False, "draft_is_web_article_video": False,
        "draft_json_file": os.path.join(draft_folder, "draft_info.json"),
        "draft_name": meta["draft_name"],
        "draft_new_version": "",
        "draft_root_path": root,
        "draft_timeline_materials_size": 0,
        "draft_type": "", "draft_web_article_video_enter_from": "",
        "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
        "tm_draft_create": meta.get("tm_draft_create", now_us),
        "tm_draft_modified": now_us, "tm_draft_removed": 0,
        "tm_duration": int(duration_us),
    }

    if os.path.isfile(rmi_path):
        with open(rmi_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"all_draft_store": [], "draft_ids": 0, "root_path": root}
    data.setdefault("all_draft_store", [])
    # 같은 폴더/같은 id의 기존 항목 제거 후 최신으로 추가
    existed = any(e.get("draft_fold_path") == draft_folder or e.get("draft_id") == draft_id
                  for e in data["all_draft_store"])
    data["all_draft_store"] = [e for e in data["all_draft_store"]
                              if e.get("draft_fold_path") != draft_folder
                              and e.get("draft_id") != draft_id]
    data["all_draft_store"].insert(0, entry)
    # draft_ids 는 리스트가 아니라 누적 카운터(int). 새 드래프트면 1 증가.
    if isinstance(data.get("draft_ids"), int):
        if not existed:
            data["draft_ids"] += 1
    else:
        data["draft_ids"] = len(data["all_draft_store"])
    data["root_path"] = root
    with open(rmi_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def refresh_template(reference_draft_folder: str) -> None:
    """CapCut이 직접 만든 참조 드래프트에서 호환 템플릿을 다시 추출한다.

    CapCut 업데이트로 draft_info.json 스키마가 바뀌면 호출:
      - 새 빈 프로젝트를 CapCut에서 만들어 저장한 폴더 경로를 넘기면
      - new_version / platform / 상위 추가키 를 그 폴더의 draft_info.json에서 다시 캡처.
    """
    ref_info = os.path.join(reference_draft_folder, "draft_info.json")
    with open(ref_info, encoding="utf-8") as f:
        ref = json.load(f)
    # 알려진 상위 추가키만 보수적으로 캡처 (버전 메타 + 4개 키)
    known_extra = ("draft_type", "function_assistant_info", "smart_ads_info",
                   "uneven_animation_template_info")
    tmpl = {
        "new_version": ref["new_version"],
        "platform": ref["platform"],
        "last_modified_platform": ref["last_modified_platform"],
        "extra_keys": {k: ref[k] for k in known_extra if k in ref},
    }
    with open(_TEMPLATE_PATH, "w", encoding="utf-8") as f:
        json.dump(tmpl, f, ensure_ascii=False, indent=2)
