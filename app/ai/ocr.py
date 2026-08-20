import re

from paddleocr import PaddleOCR

from app.ai.preprocessing import light_preprocess
from app.config import PADDLE_OCR_MODEL_DIR

# ==========================================================
# CONFIG
# ==========================================================

FALLBACK_STATE = "MH"

# ==========================================================
# OCR INIT
# ==========================================================

ocr = PaddleOCR(
    rec_model_dir=PADDLE_OCR_MODEL_DIR,
    det=False,
    use_angle_cls=False,
    use_gpu=False,
    show_log=False
)

# ==========================================================
# PLATE RULES
# ==========================================================

DIGIT_TO_LETTER = {
    "0": "D",
    "1": "I",
    "2": "Z",
    "3": "E",
    "4": "A",
    "5": "S",
    "6": "G",
    "7": "T",
    "8": "B",
    "9": "G",
}

LETTER_TO_DIGIT = {
    "O": "0",
    "Q": "0",
    "I": "1",
    "Z": "2",
    "J": "3",
    "A": "4",
    "S": "5",
    "G": "6",
    "T": "7",
    "B": "8",
}

STRICT_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{2}[0-9]{4}$")

VALID_STATES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN",
    "GA", "GJ", "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD",
    "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY", "RJ",
    "SK", "TN", "TR", "TS", "UK", "UP", "WB"
}

# ==========================================================
# TEXT CLEANING
# ==========================================================

def clean_text(text):
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def strict_plate_correction(raw_text, fallback_state=FALLBACK_STATE):
    text = clean_text(raw_text)

    if len(text) < 6:
        return text

    chars = list(text)

    while len(chars) < 10:
        chars.append("0")

    chars = chars[:10]

    # STATE
    s1 = DIGIT_TO_LETTER.get(chars[0], chars[0])
    s2 = DIGIT_TO_LETTER.get(chars[1], chars[1])
    state = s1 + s2
    if state not in VALID_STATES:
        state = fallback_state

    # DISTRICT
    d1 = LETTER_TO_DIGIT.get(chars[2], chars[2])
    d2 = LETTER_TO_DIGIT.get(chars[3], chars[3])
    if not d1.isdigit():
        d1 = "0"
    if not d2.isdigit():
        d2 = "0"

    # SERIES
    a1 = DIGIT_TO_LETTER.get(chars[4], chars[4])
    a2 = DIGIT_TO_LETTER.get(chars[5], chars[5])
    if not a1.isalpha():
        a1 = "A"
    if not a2.isalpha():
        a2 = "A"

    # NUMBER
    nums = []
    for c in chars[6:10]:
        c = LETTER_TO_DIGIT.get(c, c)
        if not c.isdigit():
            c = "0"
        nums.append(c)

    return state + d1 + d2 + a1 + a2 + "".join(nums)


# ==========================================================
# SCORING
# ==========================================================

def score_candidate(raw_text, conf):
    cleaned = clean_text(raw_text)
    corrected = strict_plate_correction(cleaned, FALLBACK_STATE)

    score = conf

    # Prefer longer useful strings, but cap at 10
    score += min(len(cleaned), 10) * 0.15

    # Boost complete lengths
    if len(cleaned) == 10:
        score += 1.5

    if len(corrected) == 10:
        score += 1.0

    # Boost regex-valid output
    if STRICT_PLATE_RE.match(corrected):
        score += 2.5

    # Boost valid state
    if len(corrected) >= 2 and corrected[:2] in VALID_STATES:
        score += 1.0

    # Penalize obvious junk length
    if len(cleaned) > 12:
        score -= 1.5

    # Penalize tiny OCR result
    if len(cleaned) <= 2:
        score -= 1.0

    return {
        "text_raw": raw_text,
        "text_clean": cleaned,
        "text_final": corrected,
        "confidence": conf,
        "score": score
    }


# ==========================================================
# OCR READ
# ==========================================================

def read_plate(img, source_name):
    try:
        result = ocr.ocr(img, det=False, cls=False)

        if not result or not result[0]:
            print(f"{source_name:<20} -> TEXT: None | CONF: 0.0000 | SCORE: 0.0000")
            return None

        raw_text = result[0][0][0]
        conf = float(result[0][0][1])

        scored = score_candidate(raw_text, conf)
        scored["source"] = source_name

        print(
            f"{source_name:<20} -> "
            f"TEXT: {scored['text_clean']} | "
            f"CONF: {scored['confidence']:.4f} | "
            f"SCORE: {scored['score']:.4f}"
        )

        return scored

    except Exception as e:
        print(f"{source_name:<20} -> ERROR: {e}")
        return None

# ==========================================================
# PUBLIC API
# ==========================================================

def run_paddleocr(img) -> dict | None:
    if img is None or img.size == 0:
        return None

    raw_result = read_plate(img, "RAW")

    light = light_preprocess(img)
    light_result = read_plate(light, "LIGHT")

    h, w = light.shape[:2]
    top = light[:h // 2, :]
    bottom = light[h // 2:, :]

    top_result = read_plate(top, "TOP")
    bottom_result = read_plate(bottom, "BOTTOM")

    combined_result = None
    if top_result and bottom_result:
        combined_text = top_result["text_clean"] + bottom_result["text_clean"]
        combined_conf = (top_result["confidence"] + bottom_result["confidence"]) / 2.0

        combined_result = score_candidate(combined_text, combined_conf)
        combined_result["source"] = "COMBINED"

        print(
            f"{'COMBINED':<20} -> "
            f"TEXT: {combined_result['text_clean']} | "
            f"CONF: {combined_result['confidence']:.4f} | "
            f"SCORE: {combined_result['score']:.4f}"
        )
    else:
        print("COMBINED             -> Not created (TOP/BOTTOM missing)")

    candidates = [
        raw_result,
        light_result,
        top_result,
        bottom_result,
        combined_result
    ]
    candidates = [c for c in candidates if c is not None]

    if not candidates:
        return None

    best = max(candidates, key=lambda x: x["score"])

    # Map to expected structure for pipeline.py:
    # { "text": ..., "text_raw": ..., "confidence": ..., "score": ... }
    return {
        "text": best["text_final"],
        "text_raw": best["text_raw"],
        "confidence": best["confidence"],
        "score": best["score"]
    }