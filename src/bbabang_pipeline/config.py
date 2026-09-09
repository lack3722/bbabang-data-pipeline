"""BBABANG ETL 공통 설정."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_DIR / ".env"

IS_AWS_LAMBDA = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

DEFAULT_DATA_DIR = (
    Path("/tmp/bbabang-data")
    if IS_AWS_LAMBDA
    else PROJECT_DIR / "data"
)

DATA_DIR = Path(os.getenv("BBABANG_DATA_DIR", str(DEFAULT_DATA_DIR)))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
QUARANTINE_DIR = DATA_DIR / "quarantine"

SEOUL_TZ = ZoneInfo("Asia/Seoul")

FIRESTORE_PROJECT_ID = "roomescape-app-mvp"
FIRESTORE_DATABASE_ID = "(default)"
FIRESTORE_COLLECTION_ID = "reviews"
FIRESTORE_RUN_QUERY_URL = (
    "https://firestore.googleapis.com/v1/projects/"
    f"{FIRESTORE_PROJECT_ID}/databases/"
    f"{FIRESTORE_DATABASE_ID}/documents:runQuery"
)

ROOM_ID_START = 4008
ROOM_ID_END = 4008
PAGE_SIZE = 10
MAX_PAGE = 500

REQUEST_TIMEOUT = 30
REQUEST_RETRY_COUNT = 3
REQUEST_BACKOFF_FACTOR = 1.0

MYSQL_TABLE_NAME = "reviews"
MYSQL_CHARSET = "utf8mb4"
MYSQL_COLLATION = "utf8mb4_unicode_ci"
MYSQL_POOL_RECYCLE = 1800
MYSQL_POOL_PRE_PING = True
MYSQL_UPSERT_CHUNK_SIZE = 500


def load_environment() -> None:
    """로컬 환경에서는 프로젝트 루트의 .env를 로드한다."""
    if ENV_FILE.is_file():
        load_dotenv(ENV_FILE)


def get_firebase_api_key() -> str | None:
    """Firestore API Key를 반환한다."""
    load_environment()
    return os.getenv("FIREBASE_API_KEY") or None


def ensure_data_directories() -> None:
    """로컬 또는 Lambda용 ETL 데이터 디렉터리를 생성한다."""
    for directory in (RAW_DIR, PROCESSED_DIR, QUARANTINE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def now_kst() -> datetime:
    """Asia/Seoul 기준 현재 시간을 반환한다."""
    return datetime.now(SEOUL_TZ)
