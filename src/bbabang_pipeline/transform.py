"""빠방 raw 리뷰 데이터를 정제하는 Transform 모듈."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import PROCESSED_DIR, QUARANTINE_DIR, ensure_data_directories

BOOLEAN_COLUMNS = {'is_nondisclosure_escaped', 'is_recommended', 'recommended', 'recommend', 'is_success', 'success', 'is_clear', 'clear'}
DATETIME_COLUMNS = {'playdate', 'created_at', 'updated_at', 'firestore_create_time', 'firestore_update_time'}
NUMERIC_COLUMNS = {'room_id', 'crawled_room_id', 'review_quality', 'participant_count', 'people', 'personnel', 'hint_count', 'hint', 'play_time', 'playtime', 'difficulty', 'difficulty_score', 'horror', 'activity', 'story', 'interior', 'rating'}


def to_snake_case(name: str) -> str:
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', str(name).strip())
    name = re.sub(r'[^0-9a-zA-Z가-힣]+', '_', name)
    return re.sub(r'_+', '_', name).strip('_').lower()


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    groups: dict[str, list[str]] = {}
    for original in df.columns:
        groups.setdefault(to_snake_case(original), []).append(original)
    result = pd.DataFrame(index=df.index)
    for normalized, originals in groups.items():
        ordered = sorted(originals, key=lambda c: 0 if c == normalized else 1)
        candidates = df[ordered]
        if len(ordered) > 1:
            conflict = candidates.apply(lambda row: row.dropna().astype(str).nunique() > 1, axis=1)
            if conflict.any():
                print(f'[Transform] {normalized} 중복 컬럼 값 충돌 {int(conflict.sum())}건')
        result[normalized] = candidates.bfill(axis=1).iloc[:, 0]
    return result


def build_standard_keys(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    if 'review_id' not in result.columns:
        result['review_id'] = pd.NA
    if 'document_name' in result.columns:
        derived = result['document_name'].astype('string').str.rsplit('/', n=1).str[-1]
        result['review_id'] = result['review_id'].fillna(derived)
    if 'room_id' not in result.columns:
        result['room_id'] = pd.NA
    if 'crawled_room_id' in result.columns:
        result['room_id'] = result['room_id'].fillna(result['crawled_room_id'])
    result['review_id'] = result['review_id'].astype('string').str.strip()
    result['room_id'] = pd.to_numeric(result['room_id'], errors='coerce').astype('Int64')
    return result


def normalize_boolean_value(value: Any) -> Any:
    if pd.isna(value):
        return pd.NA
    normalized = str(value).strip().lower()
    if normalized in {'true', '1', 'yes', 'y', 't'}:
        return True
    if normalized in {'false', '0', 'no', 'n', 'f'}:
        return False
    return pd.NA


def normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for col in result.columns:
        if col in BOOLEAN_COLUMNS or col.startswith('is_'):
            converted = result[col].map(normalize_boolean_value)
            if converted.notna().any():
                result[col] = converted.astype('boolean')
    for col in DATETIME_COLUMNS:
        if col in result.columns:
            parsed = pd.to_datetime(result[col], errors='coerce', utc=True)
            result[col] = parsed.dt.tz_convert('Asia/Seoul').dt.tz_localize(None)
    for col in NUMERIC_COLUMNS:
        if col not in result.columns:
            continue
        numeric = pd.to_numeric(result[col], errors='coerce')
        non_null = numeric.dropna()
        result[col] = numeric.astype('Int64') if (not non_null.empty and np.all(np.isclose(non_null % 1, 0))) else numeric.astype('Float64')
    return result


def serialize_nested_values(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for col in result.columns:
        result[col] = result[col].map(lambda v: json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list, tuple)) else v)
    return result


def split_quality_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    invalid_review = df['review_id'].isna() | df['review_id'].eq('')
    invalid_room = df['room_id'].isna()
    invalid = invalid_review | invalid_room
    valid_df = df.loc[~invalid].copy()
    quarantine_df = df.loc[invalid].copy()
    if not quarantine_df.empty:
        reasons = []
        for idx in quarantine_df.index:
            if invalid_review.loc[idx] and invalid_room.loc[idx]:
                reasons.append('missing_review_id_and_room_id')
            elif invalid_review.loc[idx]:
                reasons.append('missing_review_id')
            else:
                reasons.append('missing_room_id')
        quarantine_df['quarantine_reason'] = reasons
    return valid_df, quarantine_df


def deduplicate_reviews(df: pd.DataFrame) -> pd.DataFrame:
    sort_cols = [c for c in ('firestore_update_time', 'updated_at', 'created_at', 'firestore_create_time') if c in df.columns]
    result = df.sort_values(sort_cols, na_position='first') if sort_cols else df.copy()
    return result.drop_duplicates(subset=['review_id'], keep='last').reset_index(drop=True)


def run_transform(raw_csv_file: Path) -> Path:
    ensure_data_directories()
    raw_csv_file = Path(raw_csv_file)
    if not raw_csv_file.is_file():
        raise FileNotFoundError(f'raw CSV 파일이 없습니다: {raw_csv_file}')
    raw_df = pd.read_csv(raw_csv_file, low_memory=False)
    work_df = normalize_column_names(raw_df)
    work_df = build_standard_keys(work_df)
    work_df = normalize_types(work_df)
    work_df = serialize_nested_values(work_df)
    valid_df, quarantine_df = split_quality_rows(work_df)
    processed_df = deduplicate_reviews(valid_df)
    processed_df['transformed_at'] = datetime.now()
    processed_df['source_file'] = raw_csv_file.name
    if processed_df['review_id'].duplicated().any() or processed_df['review_id'].isna().any() or processed_df['room_id'].isna().any():
        raise ValueError('Transform 결과 필수키 검증에 실패했습니다.')
    batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    processed_file = PROCESSED_DIR / f'bbabang_reviews_processed_{batch_id}.csv'
    quarantine_file = QUARANTINE_DIR / f'bbabang_reviews_quarantine_{batch_id}.csv'
    processed_df.to_csv(processed_file, index=False, encoding='utf-8-sig')
    quarantine_df.to_csv(quarantine_file, index=False, encoding='utf-8-sig')
    print(f'[Transform] 저장 완료: {processed_file}')
    return processed_file
