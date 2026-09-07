import pandas as pd
import pytest

from bbabang_pipeline.load import validate_dataframe


def test_validate_dataframe_success():
    df = pd.DataFrame(
        {
            "review_id": ["R1", "R2"],
            "room_id": [4008, 4007],
        }
    )

    validate_dataframe(df)


def test_validate_dataframe_duplicate_review_id():
    df = pd.DataFrame(
        {
            "review_id": ["R1", "R1"],
            "room_id": [4008, 4008],
        }
    )

    with pytest.raises(ValueError):
        validate_dataframe(df)
