"""Transform 결과를 MySQL에 UPSERT하는 Load 모듈."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.engine import Engine


PROJECT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_DIR / ".env"
TABLE_NAME = "reviews"

REQUIRED_ENV_NAMES = {
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
}


def load_database_config() -> dict[str, str | int]:
    """프로젝트 .env에서 MySQL 연결정보를 읽는다."""
    if not ENV_FILE.is_file():
        raise FileNotFoundError(f".env 파일이 없습니다. {ENV_FILE}")

    load_dotenv(ENV_FILE)

    missing = [
        name for name in REQUIRED_ENV_NAMES
        if not os.getenv(name)
    ]
    if missing:
        raise ValueError(f"필수 환경 변수가 없습니다. {sorted(missing)}")

    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ["DB_PORT"]),
        "database": os.environ["DB_NAME"],
        "username": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
    }


def create_mysql_engine(config: dict[str, str | int]) -> Engine:
    """SQLAlchemy MySQL Engine을 생성한다."""
    db_url = URL.create(
        drivername="mysql+pymysql",
        username=str(config["username"]),
        password=str(config["password"]),
        host=str(config["host"]),
        port=int(config["port"]),
        database=str(config["database"]),
        query={"charset": "utf8mb4"},
    )

    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def quote_identifier(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def mysql_type_for_series(column: str, series: pd.Series) -> str:
    """DataFrame 컬럼 자료형을 MySQL 자료형으로 변환한다."""
    if column == "review_id":
        return "VARCHAR(255)"
    if column == "document_name":
        return "VARCHAR(1000)"
    if pd.api.types.is_bool_dtype(series.dtype):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(series.dtype):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series.dtype):
        return "DOUBLE"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "DATETIME(6)"

    lengths = series.dropna().astype(str).str.len()
    if lengths.empty:
        return "TEXT"
    if int(lengths.max()) <= 255:
        return "VARCHAR(255)"
    if int(lengths.max()) <= 4000:
        return "TEXT"
    return "LONGTEXT"


def load_processed_csv(file_path: Path) -> pd.DataFrame:
    """Processed CSV를 읽고 주요 자료형을 복원한다."""
    if not file_path.is_file():
        raise FileNotFoundError(f"processed CSV 파일이 없습니다. {file_path}")

    df = pd.read_csv(file_path, low_memory=False)

    if "review_id" in df.columns:
        df["review_id"] = df["review_id"].astype("string")
    if "room_id" in df.columns:
        df["room_id"] = pd.to_numeric(df["room_id"], errors="coerce").astype("Int64")

    for column in (
        "playdate",
        "created_at",
        "updated_at",
        "firestore_create_time",
        "firestore_update_time",
        "transformed_at",
    ):
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")

    return df


def validate_dataframe(df: pd.DataFrame) -> None:
    """MySQL 적재 전 필수키를 검증한다."""
    required = {"review_id", "room_id"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"DB 저장 필수 컬럼이 없습니다. {sorted(missing)}")
    if df["review_id"].isna().any():
        raise ValueError("review_id 결측값이 존재합니다.")
    if df["room_id"].isna().any():
        raise ValueError("room_id 결측값이 존재합니다.")
    if df["review_id"].duplicated().any():
        raise ValueError("중복 review_id가 존재합니다.")


def create_reviews_table(engine: Engine, df: pd.DataFrame) -> None:
    """reviews 테이블이 없으면 생성한다."""
    if inspect(engine).has_table(TABLE_NAME):
        return

    definitions = []

    for column in df.columns:
        sql_type = mysql_type_for_series(column, df[column])
        null_sql = "NOT NULL" if column == "review_id" else "NULL"
        definitions.append(
            f"{quote_identifier(column)} {sql_type} {null_sql}"
        )

    definitions.extend(
        [
            "PRIMARY KEY (`review_id`)",
            "`created_at_db` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "`updated_at_db` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "`last_checked_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        ]
    )

    sql = text(
        f"""
        CREATE TABLE {quote_identifier(TABLE_NAME)} (
            {", ".join(definitions)}
        )
        ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4
        COLLATE=utf8mb4_unicode_ci
        """
    )

    with engine.begin() as connection:
        connection.execute(sql)


def add_missing_columns(engine: Engine, df: pd.DataFrame) -> list[str]:
    """Processed CSV의 신규 컬럼을 기존 테이블에 추가한다."""
    existing = {
        column["name"]
        for column in inspect(engine).get_columns(TABLE_NAME)
    }
    missing = [column for column in df.columns if column not in existing]

    with engine.begin() as connection:
        for column in missing:
            sql_type = mysql_type_for_series(column, df[column])
            connection.execute(
                text(
                    f"""
                    ALTER TABLE {quote_identifier(TABLE_NAME)}
                    ADD COLUMN {quote_identifier(column)} {sql_type} NULL
                    """
                )
            )

    return missing


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame을 SQLAlchemy executemany용 records로 변환한다."""
    records: list[dict[str, Any]] = []

    for row in df.to_dict(orient="records"):
        converted: dict[str, Any] = {}

        for key, value in row.items():
            if isinstance(value, (dict, list, tuple)):
                converted[key] = json.dumps(
                    value,
                    ensure_ascii=False,
                    default=str,
                )
                continue

            if isinstance(value, pd.Timestamp):
                converted[key] = None if pd.isna(value) else value.to_pydatetime()
                continue

            if isinstance(value, np.generic):
                value = value.item()

            if value is None or pd.isna(value):
                converted[key] = None
            else:
                converted[key] = value

        records.append(converted)

    return records


def build_upsert_sql(df: pd.DataFrame):
    """review_id 기준 MySQL UPSERT SQL을 생성한다."""
    columns = df.columns.tolist()
    insert_columns = ", ".join(quote_identifier(column) for column in columns)
    bind_values = ", ".join(f":{column}" for column in columns)

    update_columns = [column for column in columns if column != "review_id"]

    # MySQL 8.0.19+의 row alias 문법을 사용한다.
    update_statements = [
        f"{quote_identifier(column)} = new.{quote_identifier(column)}"
        for column in update_columns
    ]
    update_statements.extend(
        [
            "`updated_at_db` = CURRENT_TIMESTAMP",
            "`last_checked_at` = CURRENT_TIMESTAMP",
        ]
    )

    return text(
        f"""
        INSERT INTO {quote_identifier(TABLE_NAME)}
            ({insert_columns})
        VALUES
            ({bind_values}) AS new
        ON DUPLICATE KEY UPDATE
            {", ".join(update_statements)}
        """
    )


def upsert_reviews(engine: Engine, df: pd.DataFrame, chunk_size: int = 500) -> int:
    """리뷰를 chunk 단위로 UPSERT한다."""
    records = dataframe_to_records(df)
    if not records:
        return 0

    sql = build_upsert_sql(df)
    affected = 0

    with engine.begin() as connection:
        for start in range(0, len(records), chunk_size):
            result = connection.execute(sql, records[start:start + chunk_size])
            if result.rowcount is not None:
                affected += int(result.rowcount)

    return affected


def run_load(processed_csv_file: Path) -> dict[str, int | str | bool]:
    """Processed CSV를 MySQL reviews 테이블에 적재한다."""
    processed_csv_file = Path(processed_csv_file)
    df = load_processed_csv(processed_csv_file)
    validate_dataframe(df)

    config = load_database_config()
    engine = create_mysql_engine(config)

    try:
        # DB 자체는 .env의 DB_NAME 이름으로 미리 생성되어 있어야 한다.
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        create_reviews_table(engine, df)
        added_columns = add_missing_columns(engine, df)
        affected = upsert_reviews(engine, df)

        with engine.connect() as connection:
            db_total_count = int(
                connection.execute(
                    text(f"SELECT COUNT(*) FROM {quote_identifier(TABLE_NAME)}")
                ).scalar_one()
            )

        summary = {
            "input_file": processed_csv_file.name,
            "input_count": len(df),
            "affected_row_count": affected,
            "db_total_count": db_total_count,
            "added_column_count": len(added_columns),
            "success": True,
        }

        print(f"[Load] 완료: {summary}")
        return summary

    finally:
        engine.dispose()
