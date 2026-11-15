"""Urdu patient instruction from a parsed schedule.

Produces clear, conversational Urdu instructions for patients, stating the medicine
name, formulation (Tablet, Capsule, Syrup, etc.), strength, schedule, and food
instructions in natural, polite Urdu:
e.g. "Panadol گولی 500mg: آپ نے دن میں تین بار کھانے کے بعد لینی ہے۔"
"""

UNCLEAR = "ہدایت واضح نہیں، فارماسسٹ سے تصدیق کریں۔"
TEMPLATES_REVIEWED = True

SLOT_UR = {"morning": "صبح", "noon": "دوپہر", "evening": "شام", "night": "رات کو"}
COUNT_UR = {
    "1": "ایک", "2": "دو", "3": "تین", "4": "چار", "5": "پانچ",
    "1.5": "ڈیڑھ", "2.5": "ڈھائی"
}

UNIT_UR = {
    "Tablet": "گولی", "Capsule": "کیپسول", "Syrup": "شربت", "Suspension": "شربت",
    "Injection": "انجکشن", "Drops": "قطرے", "Cream": "کریم", "Ointment": "مرہم",
    "Lotion": "لوشن", "Gel": "جیل",
    "Inhaler": "انہیلا", "Sachet": "ساشے", "Spray": "سپرے"
}

VERB_UR = {
    "Tablet": "لینی ہے",
    "Capsule": "لینا ہے",
    "Syrup": "پینا ہے",
    "Suspension": "پینا ہے",
    "Injection": "لگوانا ہے",
    "Drops": "ڈالنے ہیں",
    "Cream": "لگانی ہے",
    "Ointment": "لگانا ہے",
    "Lotion": "لگانا ہے",
    "Gel": "لگانی ہے",
    "Inhaler": "استعمال کرنا ہے",
    "Sachet": "پانی میں ملا کر پینا ہے",
    "Spray": "استعمال کرنا ہے",
}

TIMES_UR = {1: "ایک", 2: "دو", 3: "تین", 4: "چار"}
FOOD_UR = {
    "after_meal": "کھانے کے بعد",
    "before_meal": "کھانے سے پہلے",
    "empty_stomach": "نہار منہ"
}
DURATION_UR = {"days": "دن", "weeks": "ہفتے", "months": "ماہ"}


def _quantity(dose, form):
    unit = UNIT_UR.get(form, "خوراک")
    if dose == "1/2":
        return ("آدھی " if unit == "گولی" else "آدھا ") + unit
    return "%s %s" % (COUNT_UR.get(dose, dose), unit)


def _join(parts):
    if len(parts) <= 2:
        return " اور ".join(parts)
    return "، ".join(parts[:-1]) + " اور " + parts[-1]


def urdu_instruction(form, frequency, duration=None, food=None, name=None, strength=None):
    """Return {"text", "complete"}.
    Generates natural patient-friendly Urdu instructions including drug name and form."""
    form_label = UNIT_UR.get(form, "")
    verb = VERB_UR.get(form, "لینی ہے")
    clean_name = (name or "").strip()

    # Build title prefix: e.g. "Panadol گولی 500mg" or "Pregy کیپسول"
    title_parts = []
    if clean_name:
        title_parts.append(clean_name)
    if form_label:
        title_parts.append(form_label)
    if strength:
        str_val = strength.get("raw") if isinstance(strength, dict) else str(strength).strip()
        if str_val:
            title_parts.append(str_val)

    title = " ".join(title_parts)
    prefix = (title + ": ") if title else ""

    if not frequency:
        return {"text": prefix + UNCLEAR if prefix else UNCLEAR, "complete": False}

    # Eye-drops OD (right eye) check: only unclear if form is drops/unknown
    if frequency.get("ambiguous") and form in ("Drops", None):
        return {"text": prefix + UNCLEAR if prefix else UNCLEAR, "complete": False}

    schedule = frequency.get("schedule") or {}
    freq_code = frequency.get("code", "")

    # Build dosage schedule
    body = "آپ نے "
    if "slots" in schedule:
        parts = [SLOT_UR[slot] + " " + _quantity(dose, form)
                 for slot, dose in schedule["slots"].items()
                 if dose not in ("0", "0.0") and slot in SLOT_UR]
        if not parts:
            return {"text": prefix + UNCLEAR if prefix else UNCLEAR, "complete": False}
        body += _join(parts)
    elif freq_code in ("1x/day", "OD") or schedule.get("times_per_day") == 1:
        body += f"روزانہ ایک {form_label}" if form_label else "روزانہ ایک بار"
    elif freq_code in ("2x/day", "BD") or schedule.get("times_per_day") == 2:
        body += f"دن میں دو بار {form_label}" if form_label else "دن میں دو بار"
    elif freq_code in ("3x/day", "TDS") or schedule.get("times_per_day") == 3:
        body += f"دن میں تین بار {form_label}" if form_label else "دن میں تین بار"
    elif freq_code in ("4x/day", "QID") or schedule.get("times_per_day") == 4:
        body += f"دن میں چار بار {form_label}" if form_label else "دن میں چار بار"
    elif freq_code == "HS" or schedule.get("at_bedtime"):
        body += f"رات سوتے وقت ایک {form_label}" if form_label else "رات سوتے وقت"
    elif freq_code in ("1x/week", "weekly") or schedule.get("times_per_week") == 1:
        body += f"ہفتے میں ایک بار"
    elif schedule.get("as_needed"):
        body += "صرف ضرورت پڑنے پر"
    elif schedule.get("times_per_day") in TIMES_UR:
        body += f"دن میں {TIMES_UR[schedule['times_per_day']]} بار"
    else:
        return {"text": prefix + UNCLEAR if prefix else UNCLEAR, "complete": False}

    # Food timing
    if food and food.get("code") in FOOD_UR:
        body += " " + FOOD_UR[food["code"]]

    # Duration
    if duration and duration.get("unit") in DURATION_UR:
        val = duration.get("value", "")
        unit_str = DURATION_UR[duration["unit"]]
        body += f" {val} {unit_str} تک"

    # Action verb
    body += " " + verb + "۔"

    return {"text": prefix + body, "complete": True}
