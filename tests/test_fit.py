from vacancy_agent.fit import fit_vacancy, score_vacancy
from vacancy_agent.store import DirectoryFitStore


def test_shared_reno_moves_both_plans():
    model = fit_vacancy(
        [
            {"plan": "1x1", "renovated": 0, "units": 144, "vacant": 4},
            {"plan": "1x1", "renovated": 1, "units": 25, "vacant": 5},
            {"plan": "2x1", "renovated": 0, "units": 62, "vacant": 1},
            {"plan": "2x1", "renovated": 1, "units": 18, "vacant": 4},
        ]
    )
    scored = {
        (item["plan"], item["renovated"]): item["probability"] for item in model["groups"]
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
    scored = {item["plan"]: item["probability"] for item in model["groups"]}
    assert scored["1x1 B"] == 0.0
    assert scored["1x1 E"] > 0.1


def test_unknown_group_is_reported():
    model = fit_vacancy([{"plan": "1x1", "renovated": 0, "units": 10, "vacant": 1}])
    result = score_vacancy(model, "3x2", 0)
    assert result["error"] == "group_not_in_fit"


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
