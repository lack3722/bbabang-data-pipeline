"""BBABANG MySQL Load."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .database import (
    create_mysql_engine,
    dispose_engine,
    test_database_connection,
)


def validate_dataframe(df: pd.DataFrame) -> None:
    """MySQL 적재 전 기본 검증을 수행한다."""
    required = {"review_id", "room_id"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {sorted(missing)}")

    if df["review_id"].isna().any():
        raise ValueError("review_id 결측값이 존재합니다.")

    if df["room_id"].isna().any():
        raise ValueError("room_id 결측값이 존재합니다.")

    if df["review_id"].duplicated().any():
        raise ValueError("중복 review_id가 존재합니다.")


def run_load(processed_csv_file: Path) -> dict[str, int | str | bool]:
    """processed CSV를 MySQL에 적재하기 위한 진입점이다."""
    df = pd.read_csv(processed_csv_file, low_memory=False)
    validate_dataframe(df)

    engine = create_mysql_engine()

    try:
        info = test_database_connection(engine)

        return {
            "input_file": processed_csv_file.name,
            "input_count": len(df),
            "database": info["database_name"],
            "success": True,
        }

    finally:
        dispose_engine(engine)
