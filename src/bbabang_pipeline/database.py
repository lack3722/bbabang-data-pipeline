"""BBABANG ETL MySQL 연결 관리 모듈."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from .config import (
    ENV_FILE,
    MYSQL_CHARSET,
    MYSQL_POOL_PRE_PING,
    MYSQL_POOL_RECYCLE,
    load_environment,
)


REQUIRED_DB_ENV_NAMES = {
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
}


def load_database_config() -> dict[str, str | int]:
    """
    .env 파일에서 MySQL 연결 정보를 읽는다.

    Returns:
        MySQL 연결 설정 딕셔너리

    Raises:
        FileNotFoundError:
            .env 파일이 없는 경우

        ValueError:
            필수 DB 환경 변수가 누락된 경우
    """
    if not ENV_FILE.is_file():
        raise FileNotFoundError(
            f".env 파일이 없습니다: {ENV_FILE}"
        )

    load_environment()

    missing = [
        name
        for name in REQUIRED_DB_ENV_NAMES
        if not os.getenv(name)
    ]

    if missing:
        raise ValueError(
            "필수 DB 환경 변수가 없습니다: "
            f"{sorted(missing)}"
        )

    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ["DB_PORT"]),
        "database": os.environ["DB_NAME"],
        "username": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
    }


def create_mysql_engine(
    config: dict[str, str | int] | None = None,
) -> Engine:
    """
    SQLAlchemy MySQL Engine을 생성한다.

    Args:
        config:
            DB 연결 설정.
            None이면 .env에서 자동으로 읽는다.

    Returns:
        SQLAlchemy Engine
    """
    if config is None:
        config = load_database_config()

    database_url = URL.create(
        drivername="mysql+pymysql",
        username=str(config["username"]),
        password=str(config["password"]),
        host=str(config["host"]),
        port=int(config["port"]),
        database=str(config["database"]),
        query={
            "charset": MYSQL_CHARSET,
        },
    )

    return create_engine(
        database_url,
        pool_pre_ping=MYSQL_POOL_PRE_PING,
        pool_recycle=MYSQL_POOL_RECYCLE,
    )


def test_database_connection(
    engine: Engine,
) -> dict[str, Any]:
    """
    MySQL 연결 상태를 확인한다.

    Returns:
        MySQL 버전, 현재 DB, 현재 사용자 정보
    """
    query = text(
        """
        SELECT
            VERSION() AS version,
            DATABASE() AS database_name,
            CURRENT_USER() AS current_user_name
        """
    )

    with engine.connect() as connection:
        row = connection.execute(
            query
        ).mappings().one()

    return dict(row)


def dispose_engine(
    engine: Engine | None,
) -> None:
    """Engine이 존재하면 연결 풀을 정리한다."""
    if engine is not None:
        engine.dispose()
