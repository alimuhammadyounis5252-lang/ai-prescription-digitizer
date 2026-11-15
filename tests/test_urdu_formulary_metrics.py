from pathlib import Path

from rxcore.formulary import Formulary
from rxcore.metrics import cer, levenshtein, prf, wer, wilson_interval
from rxcore.parser import parse_frequency
from rxcore.urdu import UNCLEAR, urdu_instruction

ROOT = Path(__file__).resolve().parent.parent


def freq(text):
    return parse_frequency(text)[0]


# ---- Urdu -----------------------------------------------------------------
def test_urdu_from_complete_schedule():
    out = urdu_instruction("Tablet", freq("1+0+1"), None, {"code": "after_meal"})
    assert out == {"text": "صبح ایک گولی اور رات ایک گولی، کھانے کے بعد۔", "complete": True}


def test_urdu_three_times_and_half():
    assert urdu_instruction("Tablet", freq("1+1+1"))["text"] == "صبح ایک گولی، دوپہر ایک گولی اور رات ایک گولی۔"
    assert urdu_instruction("Tablet", freq("0-0-1/2"))["text"] == "رات آدھی گولی۔"
    assert urdu_instruction("Capsule", freq("1/2+0+0"))["text"] == "صبح آدھا کیپسول۔"


def test_urdu_refuses_when_missing_or_ambiguous():
    assert urdu_instruction("Tablet", None) == {"text": UNCLEAR, "complete": False}
    assert urdu_instruction("Tablet", freq("OD"))["complete"] is False
    assert urdu_instruction("Tablet", freq("HS"))["complete"] is False
    assert urdu_instruction("Tablet", freq("0+0+0"))["complete"] is False


def test_urdu_does_not_invent_quantity():
    text = urdu_instruction("Tablet", freq("BD"), {"value": 5, "unit": "days"})["text"]
    assert "دن میں دو بار" in text and "5 دن تک" in text
    assert "گولی" not in text          # BD says how often, not how many


# ---- Formulary --------------------------------------------------------------
def formulary():
    return Formulary.from_csv(ROOT / "data" / "formulary.csv")


def test_exact_match_adds_reference():
    out = formulary().lookup("capoten", {"raw": "50mg", "value": "50", "unit": "mg"})
    assert out["match_type"] == "exact" and out["entry"]["generic"] == "Captopril"
    assert out["flags"] == []


def test_unlisted_strength_is_flagged():
    out = formulary().lookup("Capoten", {"raw": "500mg", "value": "500", "unit": "mg"})
    assert [f["code"] for f in out["flags"]] == ["strength_not_listed"]


def test_bare_number_strength_matches_listed_value():
    out = formulary().lookup("Ascard", {"raw": "75", "value": "75", "unit": None})
    assert out["flags"] == []


def test_similar_name_is_only_a_suggestion():
    out = formulary().lookup("Capotin")
    assert out["match_type"] == "similar" and out["entry"] is None
    assert out["suggestions"][0]["brand"] == "Capoten"
    assert out["flags"][0]["code"] == "similar_name"


def test_unknown_name_is_not_pulled_to_a_listed_drug():
    out = formulary().lookup("Xonica")
    assert out["match_type"] == "none" and out["suggestions"] == [] and out["entry"] is None


def test_formulary_declares_itself_unverified():
    f = formulary()
    assert len(f) >= 10 and "NOT checked" in f.version
    assert not any(row["verified"] for row in f.rows)


# ---- Metrics ----------------------------------------------------------------
def test_levenshtein_and_error_rates():
    assert levenshtein("kitten", "sitting") == 3
    assert cer("capoten", "capoten") == 0
    assert round(cer("capoten", "capotin"), 4) == round(1 / 7, 4)
    assert wer("tab capoten 50mg", "tab capotin 50mg") == 1 / 3
    assert cer("abc", "") == 1.0


def test_cer_is_not_one_minus_accuracy():
    # insertions can push CER above 100%, which "100 - accuracy" can never show
    assert cer("ab", "abcdefgh") == 3.0


def test_prf_and_wilson():
    p, r, f1 = prf(8, 2, 2)
    assert (p, r) == (0.8, 0.8) and round(f1, 3) == 0.8
    _, _, f2 = prf(9, 6, 1, beta=2)
    assert f2 > prf(9, 6, 1, beta=1)[2]            # F2 rewards recall
    lo, hi = wilson_interval(9, 10)
    assert 0.55 < lo < 0.62 and 0.97 < hi < 1.0    # wide interval on 10 samples
