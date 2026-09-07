"""빠방 Firestore 리뷰 데이터를 수집하는 Extract 모듈."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import (
    FIRESTORE_RUN_QUERY_URL,
    MAX_PAGE,
    PAGE_SIZE,
    RAW_DIR,
    REQUEST_BACKOFF_FACTOR,
    REQUEST_RETRY_COUNT,
    REQUEST_TIMEOUT,
    ROOM_ID_END,
    ROOM_ID_START,
    ensure_data_directories,
    get_firebase_api_key,
)


def create_session() -> requests.Session:
    retry = Retry(
        total=REQUEST_RETRY_COUNT,
        connect=REQUEST_RETRY_COUNT,
        read=REQUEST_RETRY_COUNT,
        backoff_factor=REQUEST_BACKOFF_FACTOR,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({'POST'}),
    )
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def firestore_value_to_python(value: dict[str, Any] | None) -> Any:
    if not value:
        return None
    if 'nullValue' in value:
        return None
    if 'stringValue' in value:
        return value['stringValue']
    if 'integerValue' in value:
        return int(value['integerValue'])
    if 'doubleValue' in value:
        return float(value['doubleValue'])
    if 'booleanValue' in value:
        return bool(value['booleanValue'])
    if 'timestampValue' in value:
        return value['timestampValue']
    if 'referenceValue' in value:
        return value['referenceValue']
    if 'geoPointValue' in value:
        return value['geoPointValue']
    if 'arrayValue' in value:
        return [firestore_value_to_python(v) for v in value.get('arrayValue', {}).get('values', [])]
    if 'mapValue' in value:
        return {k: firestore_value_to_python(v) for k, v in value.get('mapValue', {}).get('fields', {}).items()}
    return value


def parse_document(document: dict[str, Any], crawled_room_id: int) -> dict[str, Any]:
    row = {k: firestore_value_to_python(v) for k, v in document.get('fields', {}).items()}
    document_name = document.get('name')
    row['document_name'] = document_name
    row['review_id'] = document_name.rsplit('/', 1)[-1] if document_name else None
    row['crawled_room_id'] = crawled_room_id
    row['firestore_create_time'] = document.get('createTime')
    row['firestore_update_time'] = document.get('updateTime')
    return row


def _field_filter(field_path: str, op: str, value: dict[str, Any]) -> dict[str, Any]:
    return {'fieldFilter': {'field': {'fieldPath': field_path}, 'op': op, 'value': value}}


def build_query(room_id: int, cursor_values: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {
        'from': [{'collectionId': 'reviews'}],
        'where': {'compositeFilter': {'op': 'AND', 'filters': [
            _field_filter('roomId', 'EQUAL', {'integerValue': str(room_id)}),
            _field_filter('isNondisclosureEscaped', 'EQUAL', {'booleanValue': False}),
        ]}},
        'orderBy': [
            {'field': {'fieldPath': 'reviewQuality'}, 'direction': 'DESCENDING'},
            {'field': {'fieldPath': 'playdate'}, 'direction': 'DESCENDING'},
            {'field': {'fieldPath': 'createdAt'}, 'direction': 'DESCENDING'},
            {'field': {'fieldPath': '__name__'}, 'direction': 'DESCENDING'},
        ],
        'limit': PAGE_SIZE,
    }
    if cursor_values:
        query['startAt'] = {'values': cursor_values, 'before': False}
    return {'structuredQuery': query}


def build_cursor(document: dict[str, Any]) -> list[dict[str, Any]]:
    fields = document.get('fields', {})
    return [
        fields.get('reviewQuality', {'nullValue': None}),
        fields.get('playdate', {'nullValue': None}),
        fields.get('createdAt', {'nullValue': None}),
        {'referenceValue': document['name']},
    ]


def fetch_room_reviews(session: requests.Session, room_id: int, api_key: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = None
    params = {'key': api_key} if api_key else None
    for _ in range(MAX_PAGE):
        response = session.post(
            FIRESTORE_RUN_QUERY_URL,
            headers={'Content-Type': 'application/json'},
            params=params,
            json=build_query(room_id, cursor),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        documents = [item['document'] for item in response.json() if 'document' in item]
        if not documents:
            break
        rows.extend(parse_document(doc, room_id) for doc in documents)
        if len(documents) < PAGE_SIZE:
            break
        cursor = build_cursor(documents[-1])
        time.sleep(0.05)
    return rows


def run_extract(room_id_start: int = ROOM_ID_START, room_id_end: int = ROOM_ID_END) -> Path:
    ensure_data_directories()
    api_key = get_firebase_api_key()
    batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    batch_dir = RAW_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    output_file = batch_dir / f'bbabang_reviews_raw_{batch_id}.csv'
    log_file = batch_dir / f'bbabang_reviews_crawl_log_{batch_id}.csv'

    all_rows: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    session = create_session()
    step = -1 if room_id_start >= room_id_end else 1
    try:
        for room_id in range(room_id_start, room_id_end + step, step):
            started_at = datetime.now()
            try:
                rows = fetch_room_reviews(session, room_id, api_key)
                all_rows.extend(rows)
                status, error_message = 'success', None
            except requests.RequestException as error:
                rows, status, error_message = [], 'failed', str(error)
            logs.append({
                'room_id': room_id,
                'status': status,
                'review_count': len(rows),
                'started_at': started_at.isoformat(timespec='seconds'),
                'finished_at': datetime.now().isoformat(timespec='seconds'),
                'error_message': error_message,
            })
            print(f'[Extract] room_id={room_id}, reviews={len(rows)}, status={status}')
    finally:
        session.close()

    raw_df = pd.DataFrame(all_rows)
    for col in raw_df.columns:
        raw_df[col] = raw_df[col].map(lambda v: json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list, tuple)) else v)
    raw_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    pd.DataFrame(logs).to_csv(log_file, index=False, encoding='utf-8-sig')
    print(f'[Extract] 저장 완료: {output_file}')
    return output_file
