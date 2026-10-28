"""score_vacancy tells the reply to use a percent, such as 73.6%."""

from vacancy_agent.fit import probability_percent, score_vacancy


def test_probability_percent_uses_one_decimal():
    assert probability_percent(0.736) == "73.6%"
    assert probability_percent(0) == "0.0%"


def test_score_result_names_the_percent_for_the_reply():
    model = {
        "reference_plan": "1x1",
        "beta0": 0.0,
        "beta_plan": {},
        "beta_reno": 0.0,
        "groups": [{"plan": "1x1", "renovated": 0, "units": 10, "vacant": 4}],
    }
    scored = score_vacancy(model, "1x1", 0)
    assert scored["percent"] == "50.0%"
    assert scored["percent"] in scored["text"]
    assert "0.5" not in scored["percent"]
