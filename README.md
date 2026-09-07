# BBABANG Review ETL Pipeline

빠방 Firestore 리뷰 데이터를 수집하고 정제한 뒤 MySQL에 저장하는 ETL 프로젝트입니다.

## 실행 흐름

```text
Firestore
  ↓
Extract
  ↓
data/raw/<batch>/*.csv
  ↓
Transform
  ↓
data/processed/*.csv
  ↓
Load
  ↓
MySQL reviews
```

## 실행

1. `.env.example`을 `.env`로 복사하고 MySQL 정보를 입력합니다.
2. MySQL에 `bbabang` 데이터베이스를 생성합니다.
3. 패키지를 설치합니다.

```bash
pip install -r requirements.txt
```

4. 실행합니다.

```bash
python main.py
```
