## ETL Pipeline

본 프로젝트는 빠방 방탈출 리뷰 데이터를 수집하여
전처리한 후 MySQL에 저장하는 ETL 데이터 파이프라인입니다.

### Extract

빠방 서비스에서 사용하는 Firestore 데이터를 직접 조회하여
리뷰 데이터를 수집합니다.

- Firestore REST API 사용
- room_id 기준 리뷰 수집
- Cursor 기반 Pagination
- 요청 실패 Retry 처리
- 수집 결과 Raw CSV 저장
- 수집 로그 저장

### Transform

수집된 Raw 데이터를 분석 및 DB 저장에 적합한 형태로 정제합니다.

- 컬럼명 snake_case 표준화
- 중복 컬럼 통합
- review_id / room_id 표준 키 생성
- Boolean 타입 변환
- Datetime 타입 변환
- Numeric 타입 변환
- review_id 기준 중복 제거
- 데이터 품질 검증
- 비정상 데이터 Quarantine 분리
- Processed CSV 저장

### Load

Transform 결과를 MySQL에 저장합니다.

- `.env` 기반 DB 설정 관리
- SQLAlchemy + PyMySQL 사용
- MySQL 연결 검증
- reviews 테이블 생성
- 신규 컬럼 자동 추가
- review_id 기준 UPSERT
- 적재 결과 검증