import hashlib
import hmac
import os
import secrets
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta


LOGIN_WINDOW_MINUTES = 15
ACCOUNT_LOCK_MINUTES = 15
IP_BAN_MINUTES = 30
MAX_FAILED_LOGINS_PER_ACCOUNT = 5
MAX_FAILED_LOGINS_PER_IP = 10

_FAILED_IP_ATTEMPTS: dict[str, deque[datetime]] = defaultdict(deque)
_BANNED_IPS: dict[str, datetime] = {}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return hmac.compare_digest(candidate.hex(), digest)


def issue_auth_token() -> str:
    return secrets.token_urlsafe(32)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def is_ip_banned(ip_address: str) -> bool:
    banned_until = _BANNED_IPS.get(ip_address)
    if not banned_until:
        return False
    if banned_until <= utc_now():
        _BANNED_IPS.pop(ip_address, None)
        return False
    return True


def register_failed_ip_attempt(ip_address: str) -> None:
    now = utc_now()
    window_start = now - timedelta(minutes=LOGIN_WINDOW_MINUTES)
    attempts = _FAILED_IP_ATTEMPTS[ip_address]

    while attempts and attempts[0] < window_start:
        attempts.popleft()

    attempts.append(now)
    if len(attempts) >= MAX_FAILED_LOGINS_PER_IP:
        _BANNED_IPS[ip_address] = now + timedelta(minutes=IP_BAN_MINUTES)
        _FAILED_IP_ATTEMPTS.pop(ip_address, None)


def clear_failed_ip_attempts(ip_address: str) -> None:
    _FAILED_IP_ATTEMPTS.pop(ip_address, None)
