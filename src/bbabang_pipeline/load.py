"""빠방 processed 리뷰를 MySQL에 적재하는 Load 모듈."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .config import MYSQL_TABLE_NAME, MYSQL_UPSERT_CHUNK_SIZE
from .database import create_mysql_engine, dispose_engine, test_database_connection


def quote_identifier(name: str) -> str:
    return '`' + name.replace('`', '``') + '`'


def mysql_type_for_series(column: str, series: pd.Series) -> str:
    if column == 'review_id':
        return 'VARCHAR(255)'
    if column == 'document_name':
        return 'VARCHAR(1000)'
    if pd.api.types.is_bool_dtype(series.dtype):
        return 'BOOLEAN'
    if pd.api.types.is_integer_dtype(series.dtype):
        return 'BIGINT'
    if pd.api.types.is_float_dtype(series.dtype):
        return 'DOUBLE'
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return 'DATETIME(6)'
    lengths = series.dropna().astype(str).str.len()
    if lengths.empty:
        return 'TEXT'
    if int(lengths.max()) <= 255:
        return 'VARCHAR(255)'
    if int(lengths.max()) <= 4000:
        return 'TEXT'
    return 'LONGTEXT'


def load_processed_csv(file_path: Path) -> pd.DataFrame:
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f'processed CSV 파일이 없습니다: {file_path}')
    df = pd.read_csv(file_path, low_memory=False)
    if 'review_id' in df.columns:
        df['review_id'] = df['review_id'].astype('string')
    if 'room_id' in df.columns:
        df['room_id'] = pd.to_numeric(df['room_id'], errors='coerce').astype('Int64')
    for col in ('playdate', 'created_at', 'updated_at', 'firestore_create_time', 'firestore_update_time', 'transformed_at'):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    return df


def validate_dataframe(df: pd.DataFrame) -> None:
    missing = {'review_id', 'room_id'} - set(df.columns)
    if missing:
        raise ValueError(f'필수 컬럼이 없습니다: {sorted(missing)}')
    if df['review_id'].isna().any() or df['room_id'].isna().any():
        raise ValueError('필수키 결측값이 존재합니다.')
    if df['review_id'].duplicated().any():
        raise ValueError('중복 review_id가 존재합니다.')


def create_reviews_table(engine: Engine, df: pd.DataFrame) -> None:
    if inspect(engine).has_table(MYSQL_TABLE_NAME):
        return
    definitions = []
    for col in df.columns:
        null_sql = 'NOT NULL' if col == 'review_id' else 'NULL'
        definitions.append(f'{quote_identifier(col)} {mysql_type_for_series(col, df[col])} {null_sql}')
    definitions.extend([
        'PRIMARY KEY (`review_id`)',
        '`created_at_db` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP',
        '`updated_at_db` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP',
        '`last_checked_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP',
    ])
    sql = text(
        f"CREATE TABLE {quote_identifier(MYSQL_TABLE_NAME)} "
        f"({', '.join(definitions)}) "
        "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    )
    with engine.begin() as conn:
        conn.execute(sql)


def add_missing_columns(engine: Engine, df: pd.DataFrame) -> list[str]:
    existing = {c['name'] for c in inspect(engine).get_columns(MYSQL_TABLE_NAME)}
    missing = [c for c in df.columns if c not in existing]
    with engine.begin() as conn:
        for col in missing:
            sql = text(
                f'ALTER TABLE {quote_identifier(MYSQL_TABLE_NAME)} '
                f'ADD COLUMN {quote_identifier(col)} {mysql_type_for_series(col, df[col])} NULL'
            )
            conn.execute(sql)
    return missing


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for row in df.to_dict(orient='records'):
        converted = {}
        for key, value in row.items():
            if isinstance(value, (dict, list, tuple)):
                converted[key] = json.dumps(value, ensure_ascii=False, default=str)
            elif isinstance(value, pd.Timestamp):
                converted[key] = None if pd.isna(value) else value.to_pydatetime()
            else:
                if isinstance(value, np.generic):
                    value = value.item()
                converted[key] = None if value is None or pd.isna(value) else value
        records.append(converted)
    return records


def build_upsert_sql(df: pd.DataFrame):
    columns = df.columns.tolist()
    insert_columns = ', '.join(quote_identifier(c) for c in columns)
    binds = ', '.join(f':{c}' for c in columns)
    updates = [f'{quote_identifier(c)} = new.{quote_identifier(c)}' for c in columns if c != 'review_id']
    updates.extend(['`updated_at_db` = CURRENT_TIMESTAMP', '`last_checked_at` = CURRENT_TIMESTAMP'])
    return text(
        f'INSERT INTO {quote_identifier(MYSQL_TABLE_NAME)} ({insert_columns}) '
        f'VALUES ({binds}) AS new '
        f"ON DUPLICATE KEY UPDATE {', '.join(updates)}"
    )


def upsert_reviews(engine: Engine, df: pd.DataFrame, chunk_size: int = MYSQL_UPSERT_CHUNK_SIZE) -> int:
    records = dataframe_to_records(df)
    if not records:
        return 0
    sql = build_upsert_sql(df)
    affected = 0
    with engine.begin() as conn:
        for start in range(0, len(records), chunk_size):
            result = conn.execute(sql, records[start:start + chunk_size])
            affected += int(result.rowcount or 0)
    return affected


def run_load(processed_csv_file: Path, engine: Engine | None = None) -> dict[str, int | str | bool]:
    df = load_processed_csv(processed_csv_file)
    validate_dataframe(df)
    owns_engine = engine is None
    if engine is None:
        engine = create_mysql_engine()
    try:
        print(f'[Load] MySQL 연결 성공: {test_database_connection(engine)}')
        create_reviews_table(engine, df)
        added_columns = add_missing_columns(engine, df)
        affected = upsert_reviews(engine, df)
        with engine.connect() as conn:
            db_total = int(conn.execute(text(f'SELECT COUNT(*) FROM {quote_identifier(MYSQL_TABLE_NAME)}')).scalar_one())
        summary = {
            'input_file': Path(processed_csv_file).name,
            'input_count': len(df),
            'affected_row_count': affected,
            'db_total_count': db_total,
            'added_column_count': len(added_columns),
            'success': True,
        }
        print(f'[Load] 완료: {summary}')
        return summary
    finally:
        if owns_engine:
            dispose_engine(engine)
