from pathlib import Path

import pytest

from vacancy_agent.parse import parse_rent_roll

ROLLS = Path(r"C:\Users\burak\Desktop\ML Interview")


def _file(pattern: str) -> Path:
    matches = [path for path in ROLLS.glob(pattern) if not path.name.startswith("~$")]
    if not matches:
        pytest.skip("rent roll is not on this machine")
    return matches[0]


def test_bay_view_plan_table():
    parsed = parse_rent_roll(_file("RentRoll-Bay*.xlsx"))
    assert parsed["property"] == "Bay View Gardens Apartments"
    assert parsed["as_of"] == "2021-05-25"
    assert parsed["units"] == 249
    assert parsed["vacant"] == 14
    groups = {(item["plan"], item["renovated"]): item for item in parsed["plans"]}
    assert groups[("1x1", 0)]["vacant"] == 4
    assert groups[("1x1", 0)]["units"] == 144
    assert groups[("1x1", 1)]["vacant"] == 5
    assert groups[("2x1", 0)]["units"] == 62
    assert groups[("2x1", 1)]["vacant"] == 4
    assert "Hello" not in str(parsed)


def test_cordoba_drops_models_and_names():
    parsed = parse_rent_roll(_file("La Cordoba*.xlsx"))
    assert parsed["property"] == "La Cordoba"
    assert parsed["as_of"] == "2021-04-30"
    assert parsed["units"] == 162
    assert parsed["vacant"] == 11
    letters = {(item["plan"], item["renovated"]) for item in parsed["plans"]}
    assert ("2x2.5 L", 0) in letters
    assert "LaPorshua" not in str(parsed)


def test_chambers_keeps_plan_codes():
    parsed = parse_rent_roll(_file("RentRoll-Chambers*.xlsx"))
    assert parsed["property"] == "Chambers Hill Elementary School"
    assert parsed["as_of"] == "2020-11-12"
    names = {item["plan"] for item in parsed["plans"]}
    assert "tb1152c2-Standard" in names
    assert all(item["renovated"] == 0 for item in parsed["plans"])
