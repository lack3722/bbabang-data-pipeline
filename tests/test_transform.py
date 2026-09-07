import pandas as pd

from bbabang_pipeline.transform import (
    build_standard_keys,
    normalize_column_names,
    to_snake_case,
)


def test_to_snake_case():
    assert to_snake_case("reviewId") == "review_id"


def test_duplicate_review_id_columns_are_coalesced():
    df = pd.DataFrame(
        {
            "review_id": [None, "A"],
            "reviewId": ["B", None],
        }
    )

    result = normalize_column_names(df)

    assert result["review_id"].tolist() == ["B", "A"]


def test_build_standard_keys_uses_crawled_room_id():
    df = pd.DataFrame(
        {
            "review_id": ["R1"],
            "crawled_room_id": [4008],
        }
    )

    result = build_standard_keys(df)

    assert int(result.loc[0, "room_id"]) == 4008
