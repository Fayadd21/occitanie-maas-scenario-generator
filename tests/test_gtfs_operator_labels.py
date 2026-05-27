import pandas as pd

from synthesis.output_resources.resources import (
    _feed_default_operator,
    _format_operator_label,
    _inherit_parent_station_operators,
    _parse_operator_labels,
)


def test_format_operator_label_single_is_plain():
    assert _format_operator_label(["Sankeo"]) == "Sankeo"
    assert _format_operator_label(["TANGO", "TANGO"]) == "TANGO"


def test_format_operator_label_multiple_is_json():
    label = _format_operator_label(["Sankeo", "TANGO"])
    assert label.startswith("[")
    assert "Sankeo" in label
    assert "TANGO" in label


def test_feed_default_operator_single_agency():
    agency = pd.DataFrame({"agency_id": ["Sankeo"], "agency_name": ["Sankeo"]})
    by_id = {"Sankeo": "Sankeo"}
    assert _feed_default_operator(agency, by_id, "gtfs") == "Sankeo"


def test_feed_default_operator_merged_feed_uses_feed_id():
    agency = pd.DataFrame(
        {
            "agency_id": ["TANGO", "Sankeo"],
            "agency_name": ["TANGO", "Sankeo"],
        }
    )
    by_id = {"TANGO": "TANGO", "Sankeo": "Sankeo"}
    assert _feed_default_operator(agency, by_id, "gtfs") == "gtfs"


def test_inherit_parent_station_operators_from_children():
    df_stops = pd.DataFrame(
        {
            "stop_id": ["1:BOCIME", "0:BOcime1"],
            "stop_name": ["Cimetiere", "Cimetiere"],
            "stop_lat": [42.734, 42.734],
            "stop_lon": [2.936, 2.936],
            "feed_id": ["gtfs", "gtfs"],
            "feed_stop_id": ["gtfs:1:BOCIME", "gtfs:0:BOcime1"],
            "operator": ["TANGO", "Sankeo"],
        }
    )
    df_meta = pd.DataFrame(
        {
            "stop_id": ["1:BOCIME", "0:BOcime1"],
            "parent_station": [None, "1:BOCIME"],
        }
    )
    operator_by_stop = dict(zip(df_stops["stop_id"].astype(str), df_stops["operator"].astype(str)))
    out = _inherit_parent_station_operators(df_stops, df_meta, operator_by_stop, "TANGO")
    assert out.loc[out["stop_id"] == "1:BOCIME", "operator"].iloc[0] == "Sankeo"


def test_parse_operator_labels_json_and_plain():
    assert _parse_operator_labels('["Sankeo"]') == ["Sankeo"]
    assert _parse_operator_labels("TANGO") == ["TANGO"]
