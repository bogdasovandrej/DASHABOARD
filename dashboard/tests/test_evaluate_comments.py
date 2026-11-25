"""A small adjudicated fixture checks denominators, missing answers and unsupported evidence."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evaluate_comments as bench  # noqa: E402


def test_same_answers_denominators_and_unsupported_quote(tmp_path):
    answer_file = tmp_path / "answers.csv"
    bench.write_csv(answer_file, ["id", "role", "qid", "text"], [
        {"id": "1", "role": "intern", "qid": "comment", "text": "Сижу до ночи, не успеваю"},
        {"id": "2", "role": "intern", "qid": "comment", "text": "В команде все помогают"},
        {"id": "3", "role": "mentor", "qid": "comment", "text": "Нужно проверить задачи"},
    ])
    def entry(id_, kind="", label="", quote="", supported=""):
        return dict(id=id_, kind=kind, label=label, quote=quote, supported=supported)

    gold = tmp_path / "gold.csv"
    bench.write_csv(gold, bench.FIELDS, [
        entry("1", "topic", "нагрузка", "Сижу до ночи", "yes"),
        entry("1", "signal", "перегруз", "Сижу до ночи", "yes"),
        entry("2", "topic", "команда", "В команде все помогают", "yes"),
        entry("3"),
    ])
    predicted = tmp_path / "predictions.csv"
    bench.write_csv(predicted, bench.FIELDS, [
        entry("1", "topic", "нагрузка", "Сижу до ночи", "yes"),
        entry("1", "signal", "перегруз", "Сижу до ночи", "yes"),
        entry("2"),
        entry("3", "topic", "команда", "Нужно проверить задачи", "no"),
    ])
    times = tmp_path / "times.csv"
    bench.write_csv(times, ["method", "processing_minutes", "human_review_minutes"], [
        {"method": method, "processing_minutes": "2", "human_review_minutes": "3"}
        for method in ("manual", "rules", "ai")
    ])
    report = bench.score(answer_file, gold,
                         {method: predicted for method in ("manual", "rules", "ai")}, times)
    assert report["answers"] == 3
    rows = report["methods"]["rules"]["per_label"]
    assert rows["topic:нагрузка"]["found"] == 1
    assert rows["topic:команда"] == {
        "found": 0, "gold_total": 1, "missed": 1, "false_alarms": 1,
        "predicted_total": 1, "unsupported": 1, "unsupported_denominator": 1,
    }
    assert report["methods"]["ai"]["minutes"]["total_minutes"] == 5
    assert {x["error"] for x in report["methods"]["rules"]["error_examples"]} == {
        "missed", "false_alarm", "unsupported_quote"}
    assert json.loads(json.dumps(report))["answers"] == 3

    bench.write_csv(predicted, bench.FIELDS, [entry("1")])
    with pytest.raises(ValueError, match="answer ids differ"):
        bench.score(answer_file, gold, {"rules": predicted}, times)


def test_two_reviewers_disagree_on_label_and_quote(tmp_path):
    a = tmp_path / "a.csv"
    bench.write_csv(a, ["id", "role", "qid", "text"],
                    [{"id": "a", "role": "intern", "qid": "q", "text": "Задач мало"}])
    x, y = tmp_path / "x.csv", tmp_path / "y.csv"
    bench.write_csv(x, bench.FIELDS, [dict(id="a", kind="topic", label="задачи", quote="Задач мало", supported="yes")])
    bench.write_csv(y, bench.FIELDS, [dict(id="a", kind="topic", label="задачи", quote="Задач", supported="yes"),
                                    dict(id="a", kind="signal", label="мало задач", quote="Задач мало", supported="yes")])
    disagreements = bench.compare_reviewers(a, x, y)
    assert disagreements["label_disagreements"] == [["a", "signal", "мало задач"]]
    assert disagreements["quote_disagreements"] == [["a", "topic", "задачи"]]
    assert disagreements["support_disagreements"] == []
