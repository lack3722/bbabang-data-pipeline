"""BBABANG Transform."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .config import (
    PROCESSED_DIR,
    QUARANTINE_DIR,
    ensure_data_directories,
)


def to_snake_case(name: str) -> str:
    """컬럼명을 snake_case로 변환한다."""
    name = str(name).strip()
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_").lower()


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼명을 snake_case로 변환하고 중복 컬럼을 병합한다."""
    groups: dict[str, list[str]] = {}

    for original in df.columns:
        normalized = to_snake_case(original)
        groups.setdefault(normalized, []).append(original)

    result = pd.DataFrame(index=df.index)

    for normalized, originals in groups.items():
        candidates = df[originals]

        if len(originals) == 1:
            result[normalized] = candidates.iloc[:, 0]
        else:
            result[normalized] = candidates.bfill(axis=1).iloc[:, 0]

    return result


def build_standard_keys(df: pd.DataFrame) -> pd.DataFrame:
    """review_id, room_id 키를 표준화한다."""
    result = df.copy()

    if "review_id" not in result.columns:
        result["review_id"] = pd.NA

    if "room_id" not in result.columns:
        result["room_id"] = pd.NA

    if "crawled_room_id" in result.columns:
        result["room_id"] = result["room_id"].fillna(
            result["crawled_room_id"]
        )

    result["review_id"] = result["review_id"].astype("string")
    result["room_id"] = pd.to_numeric(
        result["room_id"],
        errors="coerce",
    ).astype("Int64")

    return result


def run_transform(raw_csv_file: Path) -> Path:
    """raw CSV를 정제하고 processed CSV 경로를 반환한다."""
    ensure_data_directories()

    raw_df = pd.read_csv(raw_csv_file, low_memory=False)
    work_df = normalize_column_names(raw_df)
    work_df = build_standard_keys(work_df)

    invalid_mask = (
        work_df["review_id"].isna()
        | work_df["room_id"].isna()
    )

    quarantine_df = work_df.loc[invalid_mask].copy()
    processed_df = work_df.loc[~invalid_mask].copy()

    processed_df = processed_df.drop_duplicates(
        subset=["review_id"],
        keep="last",
    ).reset_index(drop=True)

    processed_file = PROCESSED_DIR / "bbabang_reviews_processed.csv"
    quarantine_file = QUARANTINE_DIR / "bbabang_reviews_quarantine.csv"

    processed_df.to_csv(
        processed_file,
        index=False,
        encoding="utf-8-sig",
    )
    quarantine_df.to_csv(
        quarantine_file,
        index=False,
        encoding="utf-8-sig",
    )

    return processed_file
