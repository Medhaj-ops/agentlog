import re

STANDARD_PATTERNS = [
    (r"sk-[a-zA-Z0-9_-]{20,}", "[REDACTED_API_KEY]"),
    (r"sk-proj-[a-zA-Z0-9_-]{20,}", "[REDACTED_API_KEY]"),
    (r"pypi-[a-zA-Z0-9_-]{20,}", "[REDACTED_TOKEN]"),
    (r"ghp_[a-zA-Z0-9]{36,}", "[REDACTED_GITHUB_TOKEN]"),
    (r"gho_[a-zA-Z0-9]{36,}", "[REDACTED_GITHUB_TOKEN]"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
    (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "[REDACTED_CARD]"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]"),
]

_compiled_patterns: list[tuple[re.Pattern, str]] = []


def configure(rules: str | list) -> None:
    """Configure redaction rules.

    Args:
        rules: Either "standard" for built-in patterns, or a list of:
            - regex strings (replaced with "[REDACTED]")
            - tuples of (regex_string, replacement_string)
    """
    global _compiled_patterns
    _compiled_patterns = []

    if rules == "standard":
        for pattern, replacement in STANDARD_PATTERNS:
            _compiled_patterns.append((re.compile(pattern), replacement))
    elif isinstance(rules, list):
        for rule in rules:
            if isinstance(rule, tuple):
                _compiled_patterns.append((re.compile(rule[0]), rule[1]))
            else:
                _compiled_patterns.append((re.compile(rule), "[REDACTED]"))


def apply(text: str) -> str:
    """Apply all configured redaction rules to text.

    If no rules are configured, returns text unchanged.
    """
    if not _compiled_patterns:
        return text
    for pattern, replacement in _compiled_patterns:
        text = pattern.sub(replacement, text)
    return text
