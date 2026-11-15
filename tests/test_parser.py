import pytest

from rxcore.parser import parse_frequency, parse_medicine_line


def codes(med):
    return {f["code"] for f in med["flags"]}


def test_full_line():
    med = parse_medicine_line("Tab. Metformin 500mg 1+0+1 after meal")
    assert med["form"] == "Tablet"
    assert med["name"] == "Metformin"
    assert (med["strength"]["value"], med["strength"]["unit"]) == ("500", "mg")
    assert med["frequency"]["schedule"]["slots"] == {"morning": "1", "noon": "0", "night": "1"}
    assert med["food"]["code"] == "after_meal"
    assert med["flags"] == []


def test_nothing_is_inferred_when_not_written():
    med = parse_medicine_line("Calcin")
    assert med["name"] == "Calcin"
    assert med["strength"] is None and med["frequency"] is None and med["duration"] is None
    assert {"strength_missing", "frequency_missing"} <= codes(med)


def test_number_without_unit_is_flagged_not_assumed():
    med = parse_medicine_line("Delanzo DR 60")
    assert med["name"] == "Delanzo DR"
    assert med["strength"]["value"] == "60" and med["strength"]["unit"] is None
    assert "strength_no_unit" in codes(med)


def test_combination_strength():
    med = parse_medicine_line("Extor 5/80mg 1-0-0")
    assert med["strength"]["value"] == "5/80"
    assert med["frequency"]["code"] == "1+0+0"


def test_half_tablet_schedule():
    med = parse_medicine_line("Disprin 300mg 0-0-1/2")
    assert med["frequency"]["schedule"]["slots"]["night"] == "1/2"


def test_dose_in_spoons_is_not_a_strength():
    med = parse_medicine_line("Syp. Hydryllin 2 tsp TDS")
    assert med["form"] == "Syrup" and med["name"] == "Hydryllin"
    assert med["strength"] is None
    assert med["dose"]["value"] == "2"
    assert med["frequency"]["code"] == "TDS"


def test_circled_number_does_not_pollute_name():
    med = parse_medicine_line("Tab-Capoten (1) 50mg")
    assert med["name"] == "Capoten" and med["strength"]["raw"] == "50mg"


@pytest.mark.parametrize("text,code", [("OD", "OD"), ("b.i.d", "BD"), ("BD", "BD"), ("TDS", "TDS"),
                                       ("t.i.d.", "TDS"), ("QID", "QID"), ("SOS", "SOS"), ("twice daily", "2x/day")])
def test_abbreviations(text, code):
    assert parse_frequency(text)[0]["code"] == code


@pytest.mark.parametrize("text", ["OD", "HS"])
def test_ambiguous_abbreviations_are_flagged(text):
    med = parse_medicine_line("Tab Alpha 10mg " + text)
    assert med["frequency"]["ambiguous"] is True
    assert "frequency_ambiguous" in codes(med)


def test_abbreviation_inside_a_word_is_not_matched():
    assert parse_frequency("Brodil")[0] is None
    assert parse_frequency("Tab Methods")[0] is None


def test_date_is_not_a_schedule():
    assert parse_frequency("10-10-26")[0] is None


def test_duration():
    med = parse_medicine_line("Cap Risek 40 mg BD x 5 days")
    assert med["duration"]["value"] == 5 and med["duration"]["unit"] == "days"


def test_unclear_line_is_critical():
    med = parse_medicine_line("Tab [?]cin 250mg BD")
    assert "line_unclear" in codes(med)
    med = parse_medicine_line("[unreadable]", unclear=True)
    assert med["name"] == "" and {"line_unclear", "name_missing"} <= codes(med)


def test_urdu_food_instruction():
    assert parse_medicine_line("Ascard 75mg 0+1+0 کھانے کے بعد")["food"]["code"] == "after_meal"
