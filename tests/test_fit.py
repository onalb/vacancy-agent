import json
from pathlib import Path

from vacancy_agent.fit import fit_vacancy, score_vacancy
from vacancy_agent.store import DirectoryFitStore
from vacancy_agent.tools import configure, load_saved, save_fit, score_saved

FITS = Path(__file__).resolve().parents[1] / "data" / "fits"
LA_CORDOBA = json.loads((FITS / "la-cordoba.json").read_text(encoding="utf-8"))
BAY_VIEW = json.loads((FITS / "bay-view-gardens-apartments.json").read_text(encoding="utf-8"))


def test_shared_reno_moves_both_plans():
    model = fit_vacancy(
        [
            {"plan": "1x1", "renovated": 0, "units": 144, "vacant": 4},
            {"plan": "1x1", "renovated": 1, "units": 25, "vacant": 5},
            {"plan": "2x1", "renovated": 0, "units": 62, "vacant": 1},
            {"plan": "2x1", "renovated": 1, "units": 18, "vacant": 4},
        ]
    )
    for group in model["groups"]:
        assert "probability" not in group
    scored = {
        (group["plan"], group["renovated"]): score_vacancy(
            model, group["plan"], group["renovated"]
        )["probability"]
        for group in model["groups"]
    }
    assert scored[("1x1", 0)] == pytest_approx(0.025)
    assert scored[("1x1", 1)] == pytest_approx(0.216)
    assert scored[("2x1", 0)] == pytest_approx(0.023)
    assert scored[("2x1", 1)] == pytest_approx(0.200)
    assert model["beta_reno"] > 1


def test_zero_vacant_plan_is_zero():
    model = fit_vacancy(
        [
            {"plan": "1x1 B", "renovated": 0, "units": 7, "vacant": 0},
            {"plan": "1x1 E", "renovated": 0, "units": 18, "vacant": 3},
        ]
    )
    for group in model["groups"]:
        assert "probability" not in group
    scored = {
        item["plan"]: score_vacancy(model, item["plan"])["probability"]
        for item in model["groups"]
    }
    assert scored["1x1 B"] == 0.0
    assert scored["1x1 E"] > 0.1


def test_unknown_group_is_reported():
    model = fit_vacancy([{"plan": "1x1", "renovated": 0, "units": 10, "vacant": 1}])
    result = score_vacancy(model, "3x2", 0)
    assert result["error"] == "group_not_in_fit"


def test_la_cordoba_scores_known_plan():
    scored = score_vacancy(LA_CORDOBA, "1x1 E", 0)
    assert "error" not in scored
    assert scored["plan"] == "1x1 E"
    assert scored["probability"] == pytest_approx(0.166)
    assert scored["vacant"] == 3
    assert scored["units"] == 18
    compact = score_vacancy(LA_CORDOBA, "1x1C")
    assert compact["plan"] == "1x1 C"
    assert compact["probability"] == pytest_approx(0.1325)
    letter = score_vacancy(LA_CORDOBA, "K")
    assert letter["plan"] == "2x2.5 K"
    ones = score_vacancy(LA_CORDOBA, "1x1")
    assert ones["error"] == "ambiguous_plan"
    assert ones["plan_keys"] == ["1x1 B", "1x1 C", "1x1 D", "1x1 E"]
    twos = score_vacancy(LA_CORDOBA, "2x2")
    assert twos["error"] == "ambiguous_plan"
    assert twos["plan_keys"] == ["2x2 F", "2x2 G", "2x2 H", "2x2 I", "2x2 J"]
    assert "error" not in score_vacancy(LA_CORDOBA, "2x2 F")
    assert score_vacancy(LA_CORDOBA, "2x2F")["plan"] == "2x2 F"
    twopoint = score_vacancy(LA_CORDOBA, "2x2.5")
    assert twopoint["error"] == "ambiguous_plan"
    assert twopoint["plan_keys"] == ["2x2.5 K", "2x2.5 L"]
    scored_c = score_vacancy(LA_CORDOBA, "1x1 C")
    assert scored_c["plan"] == "1x1 C"
    assert scored_c["probability"] == pytest_approx(0.1325)
    forgiven = score_vacancy(LA_CORDOBA, "1x1 E", 1)
    assert forgiven["plan"] == "1x1 E"
    assert forgiven["renovated"] == 0


def test_bay_view_building_only_is_ambiguous():
    blank = score_vacancy(BAY_VIEW, "")
    assert blank["error"] == "ambiguous_plan"
    assert blank["plan_keys"] == ["1x1", "2x1"]
    assert blank["plans"] == [
        {"plan": "1x1", "renovated": 0},
        {"plan": "1x1", "renovated": 1},
        {"plan": "2x1", "renovated": 0},
        {"plan": "2x1", "renovated": 1},
    ]
    assert "probability" not in blank
    ones = score_vacancy(BAY_VIEW, "1x1")
    assert ones["error"] == "ambiguous_plan"
    assert ones["plan_keys"] == ["1x1"]
    assert ones["plans"] == [
        {"plan": "1x1", "renovated": 0},
        {"plan": "1x1", "renovated": 1},
    ]
    scored = score_vacancy(BAY_VIEW, "1x1", 0)
    assert "error" not in scored
    assert scored["plan"] == "1x1"
    assert scored["renovated"] == 0
    assert scored["probability"] == pytest_approx(0.025)


def test_load_fit_hides_rates(tmp_path):
    store = DirectoryFitStore(tmp_path)
    store.save(BAY_VIEW)
    store.save(LA_CORDOBA)
    configure(store)
    view = load_saved("Bay View Gardens Apartments")
    assert view["property"] == "Bay View Gardens Apartments"
    assert view["plan_keys"] == ["1x1", "2x1"]
    assert view["plans"] == [
        {"plan": "1x1", "renovated": 0},
        {"plan": "1x1", "renovated": 1},
        {"plan": "2x1", "renovated": 0},
        {"plan": "2x1", "renovated": 1},
    ]
    dumped = json.dumps(view)
    assert "probability" not in dumped
    assert "beta0" not in dumped
    assert "beta_plan" not in dumped
    assert "beta_reno" not in dumped
    assert "groups" not in view
    blank = score_saved("Bay View Gardens Apartments")
    assert blank["error"] == "ambiguous_plan"
    assert "probability" not in blank
    unique = score_saved("Bay View Gardens Apartments", "2x1", 1)
    assert unique["plan"] == "2x1"
    assert unique["renovated"] == 1
    assert "probability" in unique


def test_score_saved_building_loads_la_cordoba(tmp_path):
    store = DirectoryFitStore(tmp_path)
    store.save(LA_CORDOBA)
    configure(store)
    scored = score_saved("La Cordoba", "1x1 E")
    assert scored["plan"] == "1x1 E"
    assert scored["probability"] == pytest_approx(0.166)
    assert "error" not in scored


def test_score_ignores_a_stored_group_probability():
    poisoned = json.loads(json.dumps(LA_CORDOBA))
    for group in poisoned["groups"]:
        group["probability"] = 0.99
    scored = score_vacancy(poisoned, "1x1 C")
    assert scored["probability"] == 0.1325
    assert scored["plan"] == "1x1 C"


def test_save_fit_omits_group_probability(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPABILITIES_GATEWAY_URL", raising=False)
    store = DirectoryFitStore(tmp_path)
    configure(store)
    model = json.loads(json.dumps(LA_CORDOBA))
    assert any("probability" in group for group in model["groups"])
    saved = save_fit.func("La Cordoba", model["as_of"], model)
    assert saved["saved"] is True
    written = json.loads((tmp_path / "la-cordoba.json").read_text(encoding="utf-8"))
    assert written["beta0"] == -3.0411
    assert written["beta_plan"]["1x1 C"] == 1.1618
    assert all("probability" not in group for group in written["groups"])
    assert all(set(group) == {"plan", "renovated", "units", "vacant"} for group in written["groups"])
    loaded = store.load("La Cordoba")
    assert all("probability" not in group for group in loaded["groups"])
    assert score_vacancy(loaded, "1x1 C")["probability"] == 0.1325


def test_save_writes_the_record_it_is_given(tmp_path):
    store = DirectoryFitStore(tmp_path)
    store.save({"property": "La Cordoba", "as_of": "2021-04-30", "groups": []})
    store.save({"property": "La Cordoba", "as_of": "2020-01-01", "groups": []})
    assert store.load("La Cordoba")["as_of"] == "2020-01-01"


def pytest_approx(value: float):
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) <= 0.03

    return _Approx()
