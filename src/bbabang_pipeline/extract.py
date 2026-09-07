"""BBABANG Firestore Extract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .config import (
    FIRESTORE_RUN_QUERY_URL,
    PAGE_SIZE,
    RAW_DIR,
    REQUEST_TIMEOUT,
    ROOM_ID_END,
    ROOM_ID_START,
    ensure_data_directories,
    get_firebase_api_key,
)


def firestore_value_to_python(value: dict[str, Any] | None) -> Any:
    """Firestore Value를 Python 값으로 변환한다."""
    if not value:
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
    if "nullValue" in value:
        return None

    return value


def parse_document(
    document: dict[str, Any],
    room_id: int,
) -> dict[str, Any]:
    """Firestore document를 일반 dict로 변환한다."""
    fields = document.get("fields", {})

    row = {
        key: firestore_value_to_python(value)
        for key, value in fields.items()
    }

    document_name = document.get("name")

    row["document_name"] = document_name
    row["review_id"] = (
        document_name.rsplit("/", 1)[-1]
        if document_name
        else None
    )
    row["crawled_room_id"] = room_id
    row["firestore_create_time"] = document.get("createTime")
    row["firestore_update_time"] = document.get("updateTime")

    return row


def build_query(room_id: int) -> dict[str, Any]:
    """빠방 리뷰 조회 StructuredQuery를 생성한다."""
    return {
        "structuredQuery": {
            "from": [{"collectionId": "reviews"}],
            "where": {
                "compositeFilter": {
                    "op": "AND",
                    "filters": [
                        {
                            "fieldFilter": {
                                "field": {"fieldPath": "roomId"},
                                "op": "EQUAL",
                                "value": {"integerValue": str(room_id)},
                            }
                        },
                        {
                            "fieldFilter": {
                                "field": {
                                    "fieldPath": "isNondisclosureEscaped"
                                },
                                "op": "EQUAL",
                                "value": {"booleanValue": False},
                            }
                        },
                    ],
                }
            },
            "orderBy": [
                {
                    "field": {"fieldPath": "reviewQuality"},
                    "direction": "DESCENDING",
                },
                {
                    "field": {"fieldPath": "playdate"},
                    "direction": "DESCENDING",
                },
                {
                    "field": {"fieldPath": "createdAt"},
                    "direction": "DESCENDING",
                },
                {
                    "field": {"fieldPath": "__name__"},
                    "direction": "DESCENDING",
                },
            ],
            "limit": PAGE_SIZE,
        }
    }


def run_extract(
    room_id_start: int = ROOM_ID_START,
    room_id_end: int = ROOM_ID_END,
) -> Path:
    """빠방 리뷰를 수집하고 raw CSV 경로를 반환한다."""
    ensure_data_directories()

    api_key = get_firebase_api_key()
    params = {"key": api_key} if api_key else None

    rows: list[dict[str, Any]] = []

    step = -1 if room_id_start >= room_id_end else 1

    with requests.Session() as session:
        for room_id in range(
            room_id_start,
            room_id_end + step,
            step,
        ):
            response = session.post(
                FIRESTORE_RUN_QUERY_URL,
                params=params,
                json=build_query(room_id),
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()

            documents = [
                item["document"]
                for item in response.json()
                if "document" in item
            ]

            rows.extend(
                parse_document(document, room_id)
                for document in documents
            )

    output_file = RAW_DIR / "bbabang_reviews_raw.csv"

    pd.DataFrame(rows).to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig",
    )

    return output_file
