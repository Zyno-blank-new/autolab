"""Redact configured credentials and recognizable credential assignments at output."""
import os
import re

SECRET_NAME = re.compile(r'api[_-]?key|token|secret|password|credential', re.I)
SECRET_VALUE = re.compile(r'sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}')
ASSIGNMENT = re.compile(r'((?:[A-Z][A-Z0-9_]*_(?:KEY|TOKEN|SECRET|PASSWORD)|password)\s*[=:]\s*)[^\s,;]+', re.I)


def public(value):
    if isinstance(value, dict):
        return {public(str(k)): '[REDACTED]' if SECRET_NAME.search(str(k)) else public(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public(x) for x in value]
    if not isinstance(value, str):
        return value
    secrets = sorted({v for k, v in os.environ.items() if SECRET_NAME.search(k) and v}, key=len, reverse=True)
    for secret in secrets:
        value = value.replace(secret, '[REDACTED]')
    value = SECRET_VALUE.sub('[REDACTED]', value)
    return ASSIGNMENT.sub(r'\1[REDACTED]', value)
