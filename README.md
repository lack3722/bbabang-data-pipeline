# BBABANG Data Pipeline

빠방(BBABANG) 방탈출 리뷰 데이터를 Firestore에서 수집하고, 데이터 정제
및 품질 검증을 수행한 뒤 MySQL 연결 단계까지 처리하는 Python 기반 ETL
데이터 파이프라인 프로젝트입니다.

> 현재 저장소의 실제 구현 상태를 기준으로 작성되었습니다.\
> `Extract → Transform → Load` 구조로 모듈을 분리하고, GitHub Actions를
> 이용한 CI 환경을 구성했습니다.

------------------------------------------------------------------------

## 1. 프로젝트 개요

빠방 서비스의 방탈출 리뷰 데이터를 데이터 분석 및 데이터베이스 활용이
가능한 형태로 수집·정제하기 위한 프로젝트입니다.

주요 목표는 다음과 같습니다.

-   Firestore REST API를 이용한 리뷰 데이터 수집
-   Raw 데이터 원본 보존
-   컬럼명 및 주요 식별자 표준화
-   데이터 품질 검증 및 비정상 데이터 분리
-   중복 리뷰 제거
-   MySQL 연결 정보와 ETL 로직 분리
-   GitHub Actions 기반 자동 코드 검증
-   ETL 단계별 모듈화를 통한 유지보수성 향상

------------------------------------------------------------------------

## 2. ETL Pipeline

``` text
BBABANG / Firestore
        │
        ▼
┌─────────────────┐
│     Extract     │
│   extract.py    │
└────────┬────────┘
         │
         ▼
      Raw CSV
         │
         ▼
┌─────────────────┐
│    Transform    │
│  transform.py   │
└────────┬────────┘
         │
         ├──────────────► Quarantine CSV
         │
         ▼
   Processed CSV
         │
         ▼
┌─────────────────┐
│      Load       │
│    load.py      │
└────────┬────────┘
         │
         ▼
  MySQL 연결/검증
```

전체 실행은 `main.py`가 담당합니다.

``` python
raw_csv_file = run_extract()
processed_csv_file = run_transform(raw_csv_file)
load_summary = run_load(processed_csv_file)
```

------------------------------------------------------------------------

## 3. 프로젝트 구조

``` text
bbabang-data-pipeline2/
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── quarantine/
│
├── src/
│   └── bbabang_pipeline/
│       ├── __init__.py
│       ├── config.py
│       ├── database.py
│       ├── extract.py
│       ├── transform.py
│       └── load.py
│
├── tests/
│   ├── test_extract.py
│   ├── test_transform.py
│   └── test_load.py
│
├── .env
├── .env.example
├── .gitignore
├── main.py
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

`.env`, `.vscode/`, Python 캐시 및 ETL 실행 결과 CSV는 `.gitignore`를
통해 Git 추적 대상에서 제외합니다.

------------------------------------------------------------------------

## 4. 모듈별 역할

  -----------------------------------------------------------------------
  파일                                역할
  ----------------------------------- -----------------------------------
  `main.py`                           Extract → Transform → Load 전체
                                      실행 순서 관리 및 예외 처리

  `config.py`                         프로젝트 경로, Firestore, 요청,
                                      MySQL 관련 공통 설정 관리

  `database.py`                       `.env` 기반 MySQL 설정 로딩,
                                      SQLAlchemy Engine 생성 및 연결
                                      테스트

  `extract.py`                        Firestore REST API 요청, 리뷰
                                      데이터 변환 및 Raw CSV 저장

  `transform.py`                      컬럼 표준화, 키 정규화, 품질 검증,
                                      중복 제거 및 CSV 저장

  `load.py`                           Processed 데이터 검증 및 MySQL 연결
                                      상태 확인

  `tests/`                            Extract, Transform, Load 주요 로직
                                      단위 테스트

  `ci.yml`                            GitHub Actions 기반 자동
                                      문법·Lint·테스트 수행
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 5. Extract

`src/bbabang_pipeline/extract.py`에서 빠방 리뷰 데이터를 수집합니다.

### 주요 기능

-   Firestore REST API 사용
-   `reviews` 컬렉션 조회
-   `roomId` 기준 리뷰 필터링
-   `isNondisclosureEscaped = false` 조건 적용
-   리뷰 정렬 조건 적용
    -   `reviewQuality DESC`
    -   `playdate DESC`
    -   `createdAt DESC`
    -   `__name__ DESC`
-   Firestore Value 형식을 Python 값으로 변환
-   Firestore document name에서 `review_id` 생성
-   수집 대상 `room_id`를 `crawled_room_id`로 기록
-   Raw CSV 저장

### Firestore 설정

공통 설정은 `config.py`에서 관리합니다.

``` python
FIRESTORE_PROJECT_ID = "roomescape-app-mvp"
FIRESTORE_DATABASE_ID = "(default)"
FIRESTORE_COLLECTION_ID = "reviews"

ROOM_ID_START = 4008
ROOM_ID_END = 4008
PAGE_SIZE = 10
```

현재 저장소 기준 수집 범위는 `4008 → 4008`로 설정되어 있습니다.

### Raw 데이터

Extract 결과는 다음 위치에 저장됩니다.

``` text
data/raw/bbabang_reviews_raw.csv
```

------------------------------------------------------------------------

## 6. Transform

`src/bbabang_pipeline/transform.py`는 Raw CSV를 데이터 분석 및 DB 처리에
적합한 형태로 정제합니다.

### 6.1 컬럼명 표준화

camelCase 등의 컬럼명을 `snake_case`로 변환합니다.

예:

``` text
reviewId    → review_id
roomId      → room_id
createdAt   → created_at
```

### 6.2 중복 컬럼 병합

Firestore 원본 필드와 수집 과정에서 추가한 필드가 동일한 snake_case
이름으로 변환될 수 있습니다.

예:

``` text
reviewId
review_id
```

이 경우 동일 의미의 컬럼을 하나로 병합합니다.

### 6.3 표준 키 생성

파이프라인에서 핵심 식별자로 사용하는 컬럼은 다음과 같습니다.

-   `review_id`
-   `room_id`

`room_id`가 없는 경우 수집 시 기록한 `crawled_room_id`를 이용하여
보완합니다.

### 6.4 Data Quality 분리

다음 조건에 해당하는 데이터는 정상 처리 대상에서 제외합니다.

-   `review_id` 결측
-   `room_id` 결측

비정상 데이터는 Quarantine CSV로 별도 저장합니다.

``` text
data/quarantine/bbabang_reviews_quarantine.csv
```

### 6.5 중복 제거

`review_id`를 기준으로 중복 데이터를 제거하고 마지막 데이터를
유지합니다.

### 6.6 Processed 데이터

정상 데이터는 다음 위치에 저장됩니다.

``` text
data/processed/bbabang_reviews_processed.csv
```

------------------------------------------------------------------------

## 7. Load / MySQL

MySQL 관련 코드는 역할에 따라 `database.py`와 `load.py`로 분리했습니다.

### database.py

다음 역할을 담당합니다.

-   `.env` 파일 로딩
-   DB 환경변수 검증
-   SQLAlchemy MySQL Engine 생성
-   MySQL 연결 테스트
-   Connection Pool 정리

사용 기술:

-   SQLAlchemy
-   PyMySQL
-   python-dotenv

MySQL 연결 문자열은 코드에 직접 작성하지 않고 환경변수로 관리합니다.

### load.py

현재 구현된 Load 단계에서는 다음을 수행합니다.

1.  Processed CSV 로드
2.  `review_id`, `room_id` 필수 컬럼 검사
3.  필수값 결측 여부 검사
4.  `review_id` 중복 여부 검사
5.  MySQL Engine 생성
6.  MySQL 연결 상태 확인
7.  Load 결과 Summary 반환

> **현재 버전의 `load.py`는 실제 `INSERT`/`UPSERT`를 수행하지
> 않습니다.**\
> MySQL 연결 및 적재 전 데이터 검증 단계까지 구현되어 있습니다. 실제
> 테이블 생성 및 UPSERT는 이후 Load 기능 확장 항목입니다.

------------------------------------------------------------------------

## 8. 환경 변수 설정

프로젝트 루트에 `.env` 파일을 생성합니다.

`.env.example` 형식:

``` env
DB_HOST=
DB_PORT=
DB_NAME=
DB_USER=
DB_PASSWORD=
```

예시:

``` env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=bbabang
DB_USER=root
DB_PASSWORD=your_password
```

실제 비밀번호가 포함된 `.env`는 GitHub에 업로드하지 않습니다.

`.gitignore`에 다음 설정이 포함되어 있습니다.

``` gitignore
.env
```

------------------------------------------------------------------------

## 9. 설치 방법

### 9.1 저장소 Clone

``` bash
git clone <repository-url>
cd bbabang-data-pipeline2
```

### 9.2 가상환경

Conda를 사용하는 경우:

``` bash
conda create -n bbabang python=3.11
conda activate bbabang
```

또는 Python venv를 사용할 수 있습니다.

``` bash
python -m venv .venv
```

Windows Git Bash:

``` bash
source .venv/Scripts/activate
```

### 9.3 패키지 설치

일반 실행에 필요한 패키지:

``` bash
pip install -r requirements.txt
```

프로젝트를 editable mode로 설치하려면:

``` bash
pip install -e .
```

CI 및 테스트 도구:

``` bash
pip install -r requirements-dev.txt
```

------------------------------------------------------------------------

## 10. 실행 방법

프로젝트 루트에서 실행합니다.

``` bash
python main.py
```

실행 흐름:

``` text
main.py
  │
  ├─ run_extract()
  │      └─ data/raw/*.csv
  │
  ├─ run_transform()
  │      ├─ data/processed/*.csv
  │      └─ data/quarantine/*.csv
  │
  └─ run_load()
         └─ MySQL 연결 및 데이터 검증
```

정상 실행 시 각 단계의 결과 파일 경로와 MySQL 처리 결과가 출력됩니다.

------------------------------------------------------------------------

## 11. 예외 처리

`main.py`에서는 단계별 주요 오류를 구분하여 처리합니다.

### Firestore 요청 오류

``` text
Firestore 요청 중 오류가 발생했습니다.
```

`requests.exceptions.RequestException` 계열의 네트워크/API 오류를
처리합니다.

### MySQL 오류

``` text
MySQL 처리 중 오류가 발생했습니다.
```

SQLAlchemy DB 처리 과정에서 발생하는 오류를 처리합니다.

### 파일 및 데이터 오류

``` text
파일 처리 또는 데이터 변환 중 오류가 발생했습니다.
```

파일 경로 또는 데이터 검증 과정의 `OSError`, `ValueError`를 처리합니다.

------------------------------------------------------------------------

## 12. 테스트

현재 테스트 파일은 다음과 같습니다.

``` text
tests/
├── test_extract.py
├── test_transform.py
└── test_load.py
```

### Extract 테스트

-   Firestore `integerValue` 변환 확인
-   `room_id`가 StructuredQuery에 정상 적용되는지 확인

### Transform 테스트

-   camelCase → snake_case 변환
-   `reviewId` / `review_id` 중복 컬럼 병합
-   `crawled_room_id`를 이용한 `room_id` 생성

### Load 테스트

-   정상 DataFrame 검증
-   중복 `review_id` 검출

테스트 실행:

``` bash
pytest -q
```

------------------------------------------------------------------------

## 13. CI - GitHub Actions

GitHub Actions 설정 파일:

``` text
.github/workflows/ci.yml
```

CI는 다음 경우 실행됩니다.

-   `main` 브랜치 Push
-   `develop` 브랜치 Push
-   `main` 브랜치 대상 Pull Request
-   `develop` 브랜치 대상 Pull Request

### CI 실행 단계

``` text
Checkout Repository
        ↓
Python 3.11 Setup
        ↓
pip Upgrade
        ↓
pip install -e .
        ↓
requirements-dev.txt 설치
        ↓
Python Syntax Check
        ↓
Ruff Lint
        ↓
pytest
```

CI에서는 다음 명령을 사용합니다.

``` bash
python -m compileall -q src main.py
ruff check src tests main.py
pytest -q
```

실제 Firestore API 요청과 MySQL 접속은 CI 단위 테스트에서 수행하지
않습니다. 외부 서비스 상태나 Secret에 의해 Pull Request 검증이
불안정해지는 것을 방지하기 위한 구성입니다.

------------------------------------------------------------------------

## 14. 주요 기술 스택

  구분               기술
  ------------------ ---------------------------------
  Language           Python 3.11+
  Data Processing    Pandas, NumPy
  HTTP               Requests
  Source             Google Cloud Firestore REST API
  Database           MySQL
  ORM / DB Toolkit   SQLAlchemy
  MySQL Driver       PyMySQL
  Environment        python-dotenv
  Test               pytest
  Lint               Ruff
  CI                 GitHub Actions
  Version Control    Git / GitHub

------------------------------------------------------------------------

## 15. 데이터 디렉터리 관리

ETL 실행 결과 데이터는 Git 저장소에 직접 포함하지 않는 것을 원칙으로
합니다.

``` text
data/
├── raw/          # Extract 원본 데이터
├── processed/    # Transform 정상 데이터
└── quarantine/   # 데이터 품질 조건을 만족하지 못한 데이터
```

`.gitignore`에서는 CSV 등 실행 결과를 제외하고 `.gitkeep`만 유지하여
디렉터리 구조를 보존합니다.

------------------------------------------------------------------------

## 16. 현재 구현 상태

  영역                상태     내용
  ------------------- -------- --------------------------------------------
  프로젝트 모듈화     완료     `src/bbabang_pipeline` 패키지 구조
  공통 설정 분리      완료     `config.py`
  DB 연결 분리        완료     `database.py`
  Firestore Extract   구현     조건 기반 리뷰 조회 및 Raw CSV 저장
  Transform           구현     컬럼 표준화, 키 정규화, DQ 분리, 중복 제거
  MySQL 연결          구현     `.env` 기반 SQLAlchemy Engine
  Load 사전 검증      구현     필수 컬럼, 결측, 중복 검사
  MySQL 실제 적재     미구현   INSERT/UPSERT 확장 필요
  Unit Test           구현     Extract / Transform / Load
  CI                  구현     compileall / Ruff / pytest

------------------------------------------------------------------------

## 17. 향후 개선 사항

현재 프로젝트를 기준으로 다음 기능을 확장할 수 있습니다.

1.  Firestore Cursor 기반 Pagination 적용
2.  HTTP Retry 및 Backoff 적용
3.  전체 `room_id` 범위 수집 설정
4.  수집 실행별 Batch ID 및 Crawl Log 관리
5.  Boolean / Datetime / Numeric 타입 정규화 강화
6.  Quarantine 사유 컬럼 추가
7.  MySQL `reviews` 테이블 자동 생성
8.  `review_id` Primary Key 기반 INSERT / UPSERT
9.  적재 후 DB 데이터 검증
10. 외부 서비스 Mock을 이용한 테스트 확대
11. GitHub Actions Integration Test 분리
12. 운영 환경 배포를 위한 CD 파이프라인 추가

------------------------------------------------------------------------

## 18. 설계 원칙

이 프로젝트는 다음 원칙을 기준으로 구성합니다.

-   **Extract와 Transform 분리**: 수집한 원본 데이터를 직접 수정하지
    않습니다.
-   **Raw 데이터 보존**: 재처리 및 오류 분석이 가능하도록 원본 데이터를
    별도로 관리합니다.
-   **설정과 로직 분리**: 공통 설정은 `config.py`, DB 연결은
    `database.py`에서 관리합니다.
-   **민감정보 분리**: DB 계정 정보는 `.env`로 관리하고 Git에 포함하지
    않습니다.
-   **단계별 책임 분리**: Extract, Transform, Load가 서로 독립적인
    책임을 갖도록 구성합니다.
-   **테스트 가능한 구조**: 외부 API와 DB 연결 없이 핵심 로직을 검증할
    수 있도록 단위 테스트를 구성합니다.
-   **CI 자동 검증**: Push와 Pull Request 시 코드 품질과 테스트 결과를
    자동 확인합니다.

------------------------------------------------------------------------

## 19. License

현재 저장소에는 별도의 라이선스 파일이 포함되어 있지 않습니다.
