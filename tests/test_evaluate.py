from evaluate import evaluate_items, score_item


def med(text, name, strength="", frequency="", flagged=False):
    return {"text": text, "name": name, "strength": strength, "frequency": frequency, "flagged": flagged}


def test_perfect_prediction():
    truth = [med("Tab Alpha 500mg 1+0+1", "Alpha", "500mg", "1+0+1")]
    s = score_item(truth, [med("Tab Alpha 500mg 1-0-1", "alpha", "500 mg", "1-0-1")])
    assert (s["tp"], s["fp"], s["fn"]) == (1, 0, 0)
    assert s["strength_correct"] == 1 and s["frequency_correct"] == 1


def test_missed_wrong_and_invented_medicines_are_counted():
    truth = [med("Alpha 5mg", "Alpha", "5mg"), med("Beta 10mg", "Beta", "10mg")]
    preds = [med("Alpha 50mg", "Alpha", "50mg"), med("Betta 10mg", "Betta", "10mg", flagged=True),
             med("Gamma", "Gamma")]
    s = score_item(truth, preds)
    assert (s["tp"], s["fp"], s["fn"]) == (1, 2, 1)
    assert s["strength_correct"] == 0                 # 50mg is not 5mg
    assert s["missed"] == ["Beta"] and s["extra"] == ["Betta", "Gamma"]
    assert (s["wrong_pred"], s["wrong_pred_flagged"]) == (2, 1)


def test_aggregate_over_images():
    items = [{"image": "a.jpg", "medicines": [med("Alpha 5mg", "Alpha", "5mg")]},
             {"image": "b.jpg", "medicines": [med("Beta 10mg", "Beta", "10mg")]}]
    answers = {"a.jpg": ([med("Alpha 5mg", "Alpha", "5mg")], "ok"), "b.jpg": ([], "unreadable")}
    summary, per_item = evaluate_items(items, lambda path: answers[path])
    assert summary["medicine_recall"] == 0.5 and summary["medicine_precision"] == 1.0
    assert summary["missed_medicine_rate"] == 0.5
    assert summary["statuses"] == {"ok": 1, "unreadable": 1}
    assert summary["medicine_recall_ci95"][0] < 0.5 < summary["medicine_recall_ci95"][1]
    assert 0 < summary["cer"] < 1 and len(per_item) == 2
