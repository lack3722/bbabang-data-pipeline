from bbabang_pipeline.extract import (
    build_query,
    firestore_value_to_python,
)


def test_firestore_integer_value():
    assert firestore_value_to_python(
        {"integerValue": "4008"}
    ) == 4008


def test_build_query_room_id():
    query = build_query(4008)

    filters = query[
        "structuredQuery"
    ]["where"]["compositeFilter"]["filters"]

    assert filters[0]["fieldFilter"]["value"] == {
        "integerValue": "4008"
    }
