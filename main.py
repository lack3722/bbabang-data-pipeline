"""
빠방 리뷰 ETL 파이프라인 실행 파일.

실행 흐름:
    Extract -> Transform -> Load(MySQL)
"""

from pathlib import Path

import requests
from sqlalchemy.exc import SQLAlchemyError

from src.bbabang_pipeline import (
    run_extract,
    run_load,
    run_transform,
)


def main() -> tuple[Path, Path, dict[str, int | str | bool]]:
    """빠방 리뷰 ETL 전체 파이프라인을 순서대로 실행한다."""
    print("=" * 70)
    print("빠방 리뷰 ETL 파이프라인 시작")
    print("=" * 70)

    # 1. Extract
    raw_csv_file = run_extract()

    # 2. Transform
    processed_csv_file = run_transform(raw_csv_file)

    # 3. Load
    load_summary = run_load(processed_csv_file)

    print()
    print(">" * 70)
    print("빠방 리뷰 ETL 파이프라인 완료")
    print(">" * 70)
    print(f"✔ raw CSV       : {raw_csv_file}")
    print(f"✔ processed CSV : {processed_csv_file}")
    print(f"✔ MySQL 결과    : {load_summary}")

    return raw_csv_file, processed_csv_file, load_summary


if __name__ == "__main__":
    try:
        main()

    except requests.exceptions.RequestException as error:
        print("Firestore 요청 중 오류가 발생했습니다.")
        print(f"오류 내용: {error}")

    except SQLAlchemyError as error:
        print("MySQL 처리 중 오류가 발생했습니다.")
        print(f"오류 내용: {error}")

    except (OSError, ValueError) as error:
        print("파일 처리 또는 데이터 변환 중 오류가 발생했습니다.")
        print(f"오류 내용: {error}")
