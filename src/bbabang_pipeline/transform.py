"""빠방 raw 리뷰 데이터를 정제하는 Transform 모듈."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
QUARANTINE_DIR = PROJECT_DIR / "data" / "quarantine"

BOOLEAN_COLUMNS = {
    "is_nondisclosure_escaped",
    "is_recommended",
    "recommended",
    "recommend",
    "is_success",
    "success",
    "is_clear",
    "clear",
}

DATETIME_COLUMNS = {
    "playdate",
    "created_at",
    "updated_at",
    "firestore_create_time",
    "firestore_update_time",
}

NUMERIC_COLUMNS = {
    "room_id",
    "crawled_room_id",
    "review_quality",
    "participant_count",
    "people",
    "personnel",
    "hint_count",
    "hint",
    "play_time",
    "playtime",
    "difficulty",
    "difficulty_score",
    "horror",
    "activity",
    "story",
    "interior",
    "rating",
}


def to_snake_case(name: str) -> str:
    """컬럼명을 snake_case로 변환한다."""
    name = str(name).strip()
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_").lower()


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """동일 의미 컬럼을 snake_case로 통합하고 중복 컬럼을 coalesce한다."""
    groups: dict[str, list[str]] = {}

    for original in df.columns:
        normalized = to_snake_case(original)
        groups.setdefault(normalized, []).append(original)

    result = pd.DataFrame(index=df.index)

    for normalized, originals in groups.items():
        # 이미 표준 이름인 컬럼을 우선 사용한다.
        ordered = sorted(originals, key=lambda name: 0 if name == normalized else 1)
        candidates = df[ordered]

        if len(ordered) == 1:
            result[normalized] = candidates.iloc[:, 0]
            continue

        conflict_mask = candidates.apply(
            lambda row: row.dropna().astype(str).nunique() > 1,
            axis=1,
        )
        if conflict_mask.any():
            print(
                f"[Transform] 주의: {normalized} 중복 컬럼 간 값 충돌 "
                f"{int(conflict_mask.sum())}건"
            )

        result[normalized] = candidates.bfill(axis=1).iloc[:, 0]

    return result


def build_standard_keys(df: pd.DataFrame) -> pd.DataFrame:
    """review_id와 room_id 표준 키를 구성한다."""
    result = df.copy()

    if "review_id" not in result.columns:
        result["review_id"] = pd.NA

    if "document_name" in result.columns:
        derived = result["document_name"].astype("string").str.rsplit("/", n=1).str[-1]
        result["review_id"] = result["review_id"].fillna(derived)

    if "room_id" not in result.columns:
        result["room_id"] = pd.NA

    if "crawled_room_id" in result.columns:
        result["room_id"] = result["room_id"].fillna(result["crawled_room_id"])

    result["review_id"] = result["review_id"].astype("string").str.strip()
    result["room_id"] = pd.to_numeric(result["room_id"], errors="coerce").astype("Int64")

    return result


def normalize_boolean_value(value: Any) -> Any:
    if pd.isna(value):
        return pd.NA

    normalized = str(value).strip().lower()

    if normalized in {"true", "1", "yes", "y", "t"}:
        return True
    if normalized in {"false", "0", "no", "n", "f"}:
        return False

    return pd.NA


def normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    """boolean, datetime, numeric 컬럼 자료형을 정규화한다."""
    result = df.copy()

    for column in result.columns:
        if column in BOOLEAN_COLUMNS or column.startswith("is_"):
            converted = result[column].map(normalize_boolean_value)
            if converted.notna().any():
                result[column] = converted.astype("boolean")

    for column in DATETIME_COLUMNS:
        if column in result.columns:
            parsed = pd.to_datetime(result[column], errors="coerce", utc=True)
            result[column] = (
                parsed.dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
            )

    for column in NUMERIC_COLUMNS:
        if column not in result.columns:
            continue

        numeric = pd.to_numeric(result[column], errors="coerce")
        non_null = numeric.dropna()

        if not non_null.empty and np.all(np.isclose(non_null % 1, 0)):
            result[column] = numeric.astype("Int64")
        else:
            result[column] = numeric.astype("Float64")

    return result


def serialize_nested_values(df: pd.DataFrame) -> pd.DataFrame:
    """dict/list/tuple 값을 JSON 문자열로 변환한다."""
    result = df.copy()

    for column in result.columns:
        result[column] = result[column].map(
            lambda value: json.dumps(value, ensure_ascii=False, default=str)
            if isinstance(value, (dict, list, tuple))
            else value
        )

    return result


def split_quality_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """필수키 기준으로 정상 데이터와 quarantine 데이터를 분리한다."""
    invalid_review_id = df["review_id"].isna() | df["review_id"].eq("")
    invalid_room_id = df["room_id"].isna()
    invalid_mask = invalid_review_id | invalid_room_id

    valid_df = df.loc[~invalid_mask].copy()
    quarantine_df = df.loc[invalid_mask].copy()

    if not quarantine_df.empty:
        quarantine_df["quarantine_reason"] = np.select(
            [
                invalid_review_id.loc[invalid_mask] & invalid_room_id.loc[invalid_mask],
                invalid_review_id.loc[invalid_mask],
                invalid_room_id.loc[invalid_mask],
            ],
            [
                "missing_review_id_and_room_id",
                "missing_review_id",
                "missing_room_id",
            ],
            default="unknown",
        )

    return valid_df, quarantine_df


def deduplicate_reviews(df: pd.DataFrame) -> pd.DataFrame:
    """review_id 기준 최신 리뷰 한 건만 남긴다."""
    result = df.copy()

    sort_columns = [
        column
        for column in (
            "firestore_update_time",
            "updated_at",
            "created_at",
            "firestore_create_time",
        )
        if column in result.columns
    ]

    if sort_columns:
        result = result.sort_values(sort_columns, na_position="first")

    return result.drop_duplicates(subset=["review_id"], keep="last").reset_index(drop=True)


def run_transform(raw_csv_file: Path) -> Path:
    """raw CSV를 정제하고 processed CSV를 저장한다."""
    raw_csv_file = Path(raw_csv_file)

    if not raw_csv_file.is_file():
        raise FileNotFoundError(f"raw CSV 파일이 없습니다. {raw_csv_file}")

    raw_df = pd.read_csv(raw_csv_file, low_memory=False)

    work_df = normalize_column_names(raw_df)
    work_df = build_standard_keys(work_df)
    work_df = normalize_types(work_df)
    work_df = serialize_nested_values(work_df)

    valid_df, quarantine_df = split_quality_rows(work_df)
    processed_df = deduplicate_reviews(valid_df)

    processed_df["transformed_at"] = datetime.now()
    processed_df["source_file"] = raw_csv_file.name

    if processed_df["review_id"].duplicated().any():
        raise ValueError("Transform 결과에 중복 review_id가 존재합니다.")
    if processed_df["review_id"].isna().any():
        raise ValueError("Transform 결과에 review_id 결측값이 존재합니다.")
    if processed_df["room_id"].isna().any():
        raise ValueError("Transform 결과에 room_id 결측값이 존재합니다.")

    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    processed_file = (
        PROCESSED_DIR / f"bbabang_reviews_processed_{batch_id}.csv"
    )
    quarantine_file = (
        QUARANTINE_DIR / f"bbabang_reviews_quarantine_{batch_id}.csv"
    )

    processed_df.to_csv(processed_file, index=False, encoding="utf-8-sig")
    quarantine_df.to_csv(quarantine_file, index=False, encoding="utf-8-sig")

    print(
        f"[Transform] raw={len(raw_df)}, processed={len(processed_df)}, "
        f"quarantine={len(quarantine_df)}"
    )
    print(f"[Transform] 저장 완료: {processed_file}")

    return processed_file
