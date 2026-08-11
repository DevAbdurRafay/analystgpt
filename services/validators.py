import re

NAME_PATTERN = re.compile(r"^[A-Za-z]+(?: [A-Za-z]+)*$")
PASSWORD_UPPER = re.compile(r"[A-Z]")
PASSWORD_LOWER = re.compile(r"[a-z]")
PASSWORD_DIGIT = re.compile(r"\d")
PASSWORD_SPECIAL = re.compile(r"[^A-Za-z0-9]")


def normalize_full_name(name: str) -> str:
    return " ".join((name or "").split())


def is_valid_full_name(name: str) -> bool:
    cleaned = normalize_full_name(name)
    if len(cleaned) < 2:
        return False
    return bool(NAME_PATTERN.match(cleaned))


def password_strength_score(password: str) -> int:
    """Return 0–4 based on uppercase, lowercase, digit, and special character rules."""
    if not password:
        return 0
    score = 0
    if PASSWORD_UPPER.search(password):
        score += 1
    if PASSWORD_LOWER.search(password):
        score += 1
    if PASSWORD_DIGIT.search(password):
        score += 1
    if PASSWORD_SPECIAL.search(password):
        score += 1
    return score


def is_valid_password(password: str) -> bool:
    return password_strength_score(password) == 4


def password_requirements_message() -> str:
    return (
        "Password must include at least one uppercase letter, "
        "one lowercase letter, one number, and one special character."
    )
