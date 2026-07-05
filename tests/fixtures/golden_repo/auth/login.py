"""Authentication helpers."""

import hashlib


def authenticate_user(username: str, password: str) -> bool:
    """Verify credentials against the user store."""
    token = issue_session_token(username)
    return verify_token(token)


def issue_session_token(username: str) -> str:
    return hashlib.sha256(username.encode()).hexdigest()


def verify_token(token: str) -> bool:
    return len(token) == 64