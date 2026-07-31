import re


def normalize_plate(text: str) -> str:
    if not text:
        return None

    text = text.upper()
    text = re.sub(r'[^A-Z0-9]', '', text)

    return text


def is_valid_plate(text: str) -> bool:
    """
    Basic Indian plate validation.
    Example: MH12AB1234
    """
    pattern = r'^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$'
    return bool(re.match(pattern, text))
