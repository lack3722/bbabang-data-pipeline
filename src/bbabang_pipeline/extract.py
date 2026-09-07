"""빠방 Firestore 리뷰 데이터를 수집하는 Extract 모듈."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_DIR / "data" / "raw"
ENV_FILE = PROJECT_DIR / ".env"

PROJECT_ID = "roomescape-app-mvp"
DATABASE_ID = "(default)"
COLLECTION_ID = "reviews"
TARGET_URL = (
    f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}"
    f"/databases/{DATABASE_ID}/documents:runQuery"
)

ROOM_ID_START = 4008
ROOM_ID_END = 2006
PAGE_SIZE = 10
MAX_PAGE = 500


def create_session() -> requests.Session:
    """재시도 정책이 적용된 HTTP Session을 생성한다."""
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"POST"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def firestore_value_to_python(value: dict[str, Any] | None) -> Any:
    """Firestore REST Value 형식을 Python 값으로 변환한다."""
    if not value:
        return None

    if "nullValue" in value:
        return None
    if "stringValue" in value:
        return value["stringValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "timestampValue" in value:
        return value["timestampValue"]
    if "referenceValue" in value:
        return value["referenceValue"]
    if "geoPointValue" in value:
        return value["geoPointValue"]
    if "arrayValue" in value:
        return [
            firestore_value_to_python(item)
            for item in value.get("arrayValue", {}).get("values", [])
        ]
    if "mapValue" in value:
        return {
            key: firestore_value_to_python(item)
            for key, item in value.get("mapValue", {}).get("fields", {}).items()
        }

    return value


def parse_document(document: dict[str, Any], crawled_room_id: int) -> dict[str, Any]:
    """Firestore document 한 건을 일반 dict로 변환한다."""
    fields = document.get("fields", {})
    row = {
        key: firestore_value_to_python(value)
        for key, value in fields.items()
    }

    document_name = document.get("name")
    row["document_name"] = document_name
    row["review_id"] = document_name.rsplit("/", 1)[-1] if document_name else None
    row["crawled_room_id"] = crawled_room_id
    row["firestore_create_time"] = document.get("createTime")
    row["firestore_update_time"] = document.get("updateTime")
    return row


def _field_filter(field_path: str, op: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "fieldFilter": {
            "field": {"fieldPath": field_path},
            "op": op,
            "value": value,
        }
    }


def build_query(room_id: int, cursor_values: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """빠방 웹앱의 리뷰 정렬 조건을 반영한 Firestore StructuredQuery를 생성한다."""
    structured_query: dict[str, Any] = {
        "from": [{"collectionId": COLLECTION_ID}],
        "where": {
            "compositeFilter": {
                "op": "AND",
                "filters": [
                    _field_filter("roomId", "EQUAL", {"integerValue": str(room_id)}),
                    _field_filter(
                        "isNondisclosureEscaped",
                        "EQUAL",
                        {"booleanValue": False},
                    ),
                ],
            }
        },
        "orderBy": [
            {"field": {"fieldPath": "reviewQuality"}, "direction": "DESCENDING"},
            {"field": {"fieldPath": "playdate"}, "direction": "DESCENDING"},
            {"field": {"fieldPath": "createdAt"}, "direction": "DESCENDING"},
            {"field": {"fieldPath": "__name__"}, "direction": "DESCENDING"},
        ],
        "limit": PAGE_SIZE,
    }

    if cursor_values:
        structured_query["startAt"] = {
            "values": cursor_values,
            "before": False,
        }

    return {"structuredQuery": structured_query}


def build_cursor(document: dict[str, Any]) -> list[dict[str, Any]]:
    """현재 페이지 마지막 document를 다음 페이지 cursor로 변환한다."""
    fields = document.get("fields", {})
    return [
        fields.get("reviewQuality", {"nullValue": None}),
        fields.get("playdate", {"nullValue": None}),
        fields.get("createdAt", {"nullValue": None}),
        {"referenceValue": document["name"]},
    ]


def fetch_room_reviews(
    session: requests.Session,
    room_id: int,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """room_id 한 개의 전체 리뷰를 cursor pagination으로 수집한다."""
    headers = {"Content-Type": "application/json"}
    params = {"key": api_key} if api_key else None

    rows: list[dict[str, Any]] = []
    cursor: list[dict[str, Any]] | None = None

    for _ in range(MAX_PAGE):
        response = session.post(
            TARGET_URL,
            headers=headers,
            params=params,
            json=build_query(room_id, cursor),
            timeout=30,
        )
        response.raise_for_status()

        payload = response.json()
        documents = [
            item["document"]
            for item in payload
            if "document" in item
        ]

        if not documents:
            break

        rows.extend(parse_document(doc, room_id) for doc in documents)

        if len(documents) < PAGE_SIZE:
            break

        cursor = build_cursor(documents[-1])
        time.sleep(0.05)

    return rows


def run_extract(
    room_id_start: int = ROOM_ID_START,
    room_id_end: int = ROOM_ID_END,
) -> Path:
    """Firestore 리뷰를 수집하고 배치별 raw CSV를 저장한다."""
    load_dotenv(ENV_FILE)
    api_key = os.getenv("FIREBASE_API_KEY") or None

    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_batch_dir = RAW_DIR / batch_id
    raw_batch_dir.mkdir(parents=True, exist_ok=True)

    output_file = raw_batch_dir / f"bbabang_reviews_raw_{batch_id}.csv"
    log_file = raw_batch_dir / f"bbabang_reviews_crawl_log_{batch_id}.csv"

    session = create_session()
    all_rows: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []

    step = -1 if room_id_start >= room_id_end else 1

    try:
        for room_id in range(room_id_start, room_id_end + step, step):
            started_at = datetime.now()

            try:
                rows = fetch_room_reviews(session, room_id, api_key)
                all_rows.extend(rows)
                status = "success"
                error_message = None
            except requests.RequestException as error:
                rows = []
                status = "failed"
                error_message = str(error)

            logs.append(
                {
                    "room_id": room_id,
                    "status": status,
                    "review_count": len(rows),
                    "started_at": started_at.isoformat(timespec="seconds"),
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error_message": error_message,
                }
            )

            print(f"[Extract] room_id={room_id} / reviews={len(rows)} / {status}")

    finally:
        session.close()

    raw_df = pd.DataFrame(all_rows)

    # dict/list가 포함되어도 CSV 저장 가능하도록 JSON 문자열화
    for column in raw_df.columns:
        raw_df[column] = raw_df[column].map(
            lambda value: json.dumps(value, ensure_ascii=False, default=str)
            if isinstance(value, (dict, list, tuple))
            else value
        )

    raw_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    pd.DataFrame(logs).to_csv(log_file, index=False, encoding="utf-8-sig")

    print(f"[Extract] 저장 완료: {output_file}")
    return output_file
