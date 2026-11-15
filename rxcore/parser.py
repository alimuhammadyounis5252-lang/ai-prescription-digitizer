"""Deterministic parsing of one transcribed prescription line into fields.

Design rule: a field is filled only when the text contains it. Nothing is
inferred. Whatever cannot be parsed stays visible in `raw_text`.
"""
import re

FORMS = {
    "tab": "Tablet", "tabs": "Tablet", "tablet": "Tablet", "tablets": "Tablet",
    "cap": "Capsule", "caps": "Capsule", "capsule": "Capsule", "capsules": "Capsule",
    "gp": "Capsule", "cp": "Capsule",
    "syp": "Syrup", "syr": "Syrup", "syrup": "Syrup",
    "susp": "Suspension", "suspension": "Suspension",
    "inj": "Injection", "injection": "Injection",
    "drops": "Drops", "drop": "Drops",
    "cream": "Cream", "oint": "Ointment", "ointment": "Ointment",
    "lotion": "Lotion", "gel": "Gel", "sachet": "Sachet",
    "inh": "Inhaler", "inhaler": "Inhaler", "spray": "Spray",
}

_DOSE = r"(?:\d/\d|\d(?:\.\d)?|½)"
RE_TRIPLE = re.compile(
    r"(?<![\d/.])(" + _DOSE + r")\s*([+\-–])\s*(" + _DOSE + r")\s*\2\s*(" + _DOSE + r")"
    r"(?:\s*\2\s*(" + _DOSE + r"))?(?![\d/])")
_UNITS_AFTER = r"(?!\s*(?:days?|weeks?|wks?|months?|din|hafte|hafta|mah|mg|ml|g\b))"
RE_TIMES = re.compile(r"(?<![\w/.+\-–])(\d|½|1/2)\s*[x×]\s*(\d)(?![\d/.])" + _UNITS_AFTER, re.I)
RE_PAIR = re.compile(r"(?<![\w/.+\-–])(" + _DOSE + r")\s*\+\s*(" + _DOSE + r")(?![\d/+])")
RE_INSTRUCTION = re.compile(r"\b(apply|take|use|locally|daily|morning|evening|night|bedtime|subah|sham|raat)\b", re.I)
RE_ABBR = re.compile(
    r"(?<![A-Za-z.])(o\.?d|b\.?i\.?d|b\.?d|t\.?d\.?s|t\.?i\.?d|q\.?i\.?d|q\.?d\.?s|"
    r"h\.?s|s\.?o\.?s|p\.?r\.?n|stat)\.?(?![A-Za-z])", re.I)
RE_WORDS = re.compile(
    r"\b(once|twice|thrice)\s+(?:a\s+day|daily)\b|\b(\d)\s*times\s+(?:a|per)?\s*day\b", re.I)
# Optional "/5ml" part keeps syrup concentrations whole: "120mg/5ml" is one strength.
RE_STRENGTH = re.compile(
    r"(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*"
    r"((?:mg|mcg|µg|gm|g|ml|iu|units?|%)(?:\s*/\s*\d*(?:\.\d+)?\s*(?:ml|mg|g|l)(?![A-Za-z]))?)(?![A-Za-z])", re.I)
RE_BARE_NUMBER = re.compile(r"(?<![\w/+\-–.])(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)(?![\w/+\-–.])")
RE_DURATION = re.compile(
    r"(?:\b(?:x|for)\s*|×\s*)?(\d+)\s*(days?|weeks?|wks?|months?|din|hafte|hafta|mah|دن|ہفتے|ہفتہ|ماہ)(?![A-Za-z])",
    re.I)
RE_QUANTITY = re.compile(r"\(\s*(\d{1,3})\s*\)")
RE_DOSE_UNIT = re.compile(
    r"(?<![\d/.])(\d(?:/\d|\.\d)?|½)\s*(tsp|tbsp|teaspoons?|tablespoons?|spoons?|chamm?a?ch|"
    r"drops?|puffs?|چمچ|قطرے)(?![A-Za-z])", re.I)
RE_LEADING = re.compile(r"^\s*(?:[\-–—•*→>:~①②③④⑤⑥⑦⑧⑨⑩]+|\(?\d{1,2}[.)\s]|rx[:.]?|℞)\s*", re.I)

URDU_FREQ_PATTERNS = [
    (re.compile(r"صبح\s*دوپہر\s*(?:اور\s*)?شام|تین\s*(?:بار|ٹائم)\s*روزانہ|دن\s*میں\s*تین\s*بار", re.I),
     {"code": "1+1+1", "schedule": {"slots": {"morning": "1", "noon": "1", "night": "1"}}, "ambiguous": False, "note": None}),
    (re.compile(r"صبح\s*(?:اور\s*)?شام|مورننگ\s*و\s*نائٹ|دو\s*(?:بار|ٹائم)\s*روزانہ|دن\s*میں\s*دو\s*بار", re.I),
     {"code": "1+0+1", "schedule": {"slots": {"morning": "1", "noon": "0", "night": "1"}}, "ambiguous": False, "note": None}),
    (re.compile(r"روزانہ\s*(?:1|ایک)\s*(?:گولی|کیپسول|چمچ|خوراک)?|(?:1|ایک)\s*بار\s*روزانہ|روزانہ|ہر\s*روز", re.I),
     {"code": "OD", "schedule": {"times_per_day": 1}, "ambiguous": False, "note": None}),
    (re.compile(r"رات\s*(?:کو\s*)?(?:سوتے\s*وقت)?|سوتے\s*وقت", re.I),
     {"code": "HS", "schedule": {"at_bedtime": True}, "ambiguous": False, "note": None}),
    (re.compile(r"ہفتہ\s*(?:1|ایک)\s*(?:روز|بار)|ہفتے\s*میں\s*(?:1|ایک)\s*بار", re.I),
     {"code": "1x/week", "schedule": {"times_per_week": 1}, "ambiguous": False, "note": None}),
]

FOOD_PATTERNS = [
    ("empty_stomach", re.compile(r"empty\s+stomach|neh?ar\s+mu?n?h|نہار\s*منہ", re.I)),
    ("after_meal", re.compile(r"after\s+(?:meals?|food|breakfast|lunch|dinner)|\bp\.c\.?(?![A-Za-z])|"
                              r"kha+ne?\s+ke\s+ba+d|کھانے\s+کے\s+بعد|ناشتے?\s+کے\s+بعد", re.I)),
    ("before_meal", re.compile(r"before\s+(?:meals?|food|breakfast|lunch|dinner)|\ba\.c\.?(?![A-Za-z])|"
                               r"kha+ne?\s+se\s+pe?h?le|کھانے\s+سے\s+پہلے", re.I)),
]

ABBR = {
    "od": ("OD", {"times_per_day": 1}, True,
           "OD usually means once daily but can also mean right eye. Confirm."),
    "bd": ("BD", {"times_per_day": 2}, False, None),
    "bid": ("BD", {"times_per_day": 2}, False, None),
    "tds": ("TDS", {"times_per_day": 3}, False, None),
    "tid": ("TDS", {"times_per_day": 3}, False, None),
    "qid": ("QID", {"times_per_day": 4}, False, None),
    "qds": ("QID", {"times_per_day": 4}, False, None),
    "hs": ("HS", {"at_bedtime": True}, True,
           "HS usually means at bedtime but can also mean half strength. Confirm."),
    "sos": ("SOS", {"as_needed": True}, False, None),
    "prn": ("PRN", {"as_needed": True}, False, None),
    "stat": ("STAT", {"single_dose_now": True}, False, None),
}
WORD_TIMES = {"once": 1, "twice": 2, "thrice": 3}


def _flag(code, message, severity):
    return {"code": code, "message": message, "severity": severity}


def parse_frequency(text):
    """Return (frequency dict or None, span or None).

    frequency = {"raw", "code", "schedule", "ambiguous", "note"}
    schedule is one of:
      {"slots": {"morning": "1", "noon": "0", "night": "1"}}   from 1+0+1
      {"times_per_day": n} | {"as_needed": True} | {"at_bedtime": True} | ...
    """
    text = text or ""
    # Check Urdu dosing patterns
    for pat, item in URDU_FREQ_PATTERNS:
        m = pat.search(text)
        if m:
            d = dict(item)
            d["raw"] = m.group(0)
            return d, m.span()

    m = RE_TRIPLE.search(text)
    if m:
        doses = [d for d in (m.group(1), m.group(3), m.group(4), m.group(5)) if d is not None]
        doses = ["1/2" if d == "½" else d for d in doses]
        names = ["morning", "noon", "night"] if len(doses) == 3 else ["morning", "noon", "evening", "night"]
        return ({"raw": m.group(0), "code": "+".join(doses),
                 "schedule": {"slots": dict(zip(names, doses))},
                 "ambiguous": False, "note": None}, m.span())
    m = RE_ABBR.search(text)
    if m:
        key = m.group(1).replace(".", "").lower()
        code, schedule, ambiguous, note = ABBR[key]
        return ({"raw": m.group(0), "code": code, "schedule": dict(schedule),
                 "ambiguous": ambiguous, "note": note}, m.span())
    m = RE_WORDS.search(text)
    if m:
        n = WORD_TIMES[m.group(1).lower()] if m.group(1) else int(m.group(2))
        return ({"raw": m.group(0), "code": "%dx/day" % n, "schedule": {"times_per_day": n},
                 "ambiguous": False, "note": None}, m.span())
    m = RE_TIMES.search(text)
    if m:
        return ({"raw": m.group(0), "code": "%sx%s" % (m.group(1), m.group(2)),
                 "schedule": {"times_per_day": int(m.group(2))}, "ambiguous": True,
                 "note": "'%s' was read as %s unit(s), %s times a day. Confirm, then write it as 1+0+1 style."
                         % (m.group(0), m.group(1), m.group(2))}, m.span())
    m = RE_PAIR.search(text)
    if m:
        return ({"raw": m.group(0), "code": "%s+%s" % (m.group(1), m.group(2)),
                 "schedule": {"times_per_day": 2}, "ambiguous": True,
                 "note": "'%s' has two parts, so the times of day are not stated. Confirm and write all three (1+0+1)."
                         % m.group(0)}, m.span())
    return None, None


def parse_duration(text):
    m = RE_DURATION.search(text or "")
    if not m:
        return None, None
    unit = m.group(2).lower()
    if unit.startswith(("day", "din")) or unit == "دن":
        unit = "days"
    elif unit.startswith(("week", "wk", "haft")) or unit in ("ہفتے", "ہفتہ"):
        unit = "weeks"
    else:
        unit = "months"
    return {"raw": m.group(0).strip(), "value": int(m.group(1)), "unit": unit}, m.span()


def parse_food(text):
    for code, pattern in FOOD_PATTERNS:
        m = pattern.search(text or "")
        if m:
            return {"raw": m.group(0), "code": code}, m.span()
    return None, None


def parse_medicine_line(raw_text, unclear=False):
    """Parse one medicine line. Returns a dict with fields and flags."""
    raw_text = (raw_text or "").strip()
    flags = []
    work = RE_LEADING.sub("", raw_text).strip()
    work = re.sub(r"^\d+\s+", "", work).strip()

    form = None
    m = re.match(r"([A-Za-z]+)\s*[.\-:]?\s*", work)
    if m and m.group(1).lower() in FORMS:
        form = FORMS[m.group(1).lower()]
        work = work[m.end():].strip()
    else:
        m = re.match(r"([TtCc])\.\s*(?=[A-Za-z])", work)    # "T. Panadol", "C. Risek"
        if m:
            form = "Tablet" if m.group(1).lower() == "t" else "Capsule"
            work = work[m.end():].strip()

    # Check form word anywhere in the line (e.g. "Clotrim Cream", "Voltral Gel")
    if not form:
        for f_word, f_name in FORMS.items():
            pattern = r"\b" + re.escape(f_word) + r"\b"
            m_f = re.search(pattern, work, re.I)
            if m_f:
                form = f_name
                work = (work[:m_f.start()].strip() + " " + work[m_f.end():].strip()).strip()
                break

    spans = []
    frequency, span = parse_frequency(work)
    if span:
        spans.append(span)

    def masked(text):
        chars = list(text)
        for a, b in spans:
            chars[a:b] = " " * (b - a)
        return "".join(chars)

    duration, span = parse_duration(masked(work))
    if span:
        spans.append(span)
    food, span = parse_food(masked(work))
    if span:
        spans.append(span)

    circled_number = None
    m = RE_QUANTITY.search(work)
    if m:
        circled_number = {"raw": m.group(0), "value": int(m.group(1))}
        spans.append(m.span())
    dose = None
    m = RE_DOSE_UNIT.search(work)
    if m:
        dose = {"raw": m.group(0), "value": m.group(1), "unit": m.group(2).lower()}
        spans.append(m.span())

    m = RE_INSTRUCTION.search(work)
    if m and work[:m.start()].strip():
        spans.append((m.start(), m.end()))

    rest = masked(work)
    strength = None
    m = RE_STRENGTH.search(rest)
    if m:
        value = re.sub(r"\s+", "", m.group(1))
        strength = {"raw": m.group(0), "value": value, "unit": re.sub(r"\s+", "", m.group(2)).lower(),
                    "unit_written": True}
        spans.append(m.span())
    else:
        m = RE_BARE_NUMBER.search(rest)
        # A bare number counts as a strength only when it follows a name.
        if m and rest[:m.start()].strip():
            strength = {"raw": m.group(0), "value": m.group(1), "unit": None, "unit_written": False}
            spans.append(m.span())
            flags.append(_flag("strength_no_unit",
                               "A number is written without a unit (mg/ml). Confirm the strength.", "warning"))

    cut = min([a for a, _ in spans], default=len(work))
    name = re.sub(r"[\s,;:.\-–—•*~()لگائیںپئیںکھائیں]+$", "", work[:cut]).strip()
    name = re.sub(r"^[\s,;:.\-–—•*~()]+", "", name).strip()
    name = re.sub(r"^\d+\s+", "", name).strip()
    name = re.sub(r"\s+", " ", name)
    if name.lower() == "[unreadable]":
        name = ""

    if unclear or "[?]" in raw_text or "[unreadable]" in raw_text.lower():
        flags.append(_flag("line_unclear",
                           "The model was not sure about this line. Read it from the original.", "critical"))
    if not name:
        flags.append(_flag("name_missing", "No medicine name could be read on this line.", "critical"))
    if strength is None:
        flags.append(_flag("strength_missing", "No strength is written on this line.", "warning"))
    if frequency is None:
        flags.append(_flag("frequency_missing", "No dosing frequency is written on this line.", "warning"))
    elif frequency["ambiguous"]:
        flags.append(_flag("frequency_ambiguous", frequency["note"], "warning"))

    return {
        "raw_text": raw_text,
        "form": form,
        "name": name,
        "strength": strength,
        "frequency": frequency,
        "duration": duration,
        "food": food,
        "dose": dose,
        "circled_number": circled_number,
        "flags": flags,
    }
