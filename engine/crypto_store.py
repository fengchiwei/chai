"""v2.3 Phase 2: field-level encryption at rest for SQLite.

- Key: env ANLA_DB_KEY (any passphrase; stretched with PBKDF2-HMAC-SHA256), otherwise a random
  key file created next to the database (`<db>.key`). Keep that file out of backups/repos;
  losing it makes encrypted rows unreadable.
- Cipher: AES-256-GCM via `cryptography` ("enc:v1:"). If the package is missing, a standard-library
  encrypt-then-MAC construction (HMAC-SHA256 counter keystream + HMAC-SHA256 tag, "enc:v0:") is used
  so the app still never writes plaintext. v1 is preferred; both are authenticated.
- Values without the "enc:" prefix are legacy plaintext and are returned unchanged.
"""
import base64
import hashlib
import hmac
import os
import secrets
import threading

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - exercised by forcing the fallback in tests
    AESGCM = None

PREFIX = "enc:"
_SALT = b"anla-youth-db-v1"
_PBKDF2_ROUNDS = 200_000
_lock = threading.Lock()
_cache = {}


class DecryptionError(ValueError):
    pass


def _key_file(db_path):
    return os.path.abspath(db_path) + ".key"


def _master_key(db_path):
    passphrase = os.environ.get("ANLA_DB_KEY", "")
    cache_key = ("env", passphrase) if passphrase else ("file", _key_file(db_path))
    with _lock:
        if cache_key in _cache:
            return _cache[cache_key]
        if passphrase:
            key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), _SALT, _PBKDF2_ROUNDS)
        else:
            path = _key_file(db_path)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    key = base64.b64decode(f.read().strip())
            else:
                key = secrets.token_bytes(32)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(base64.b64encode(key))
            if len(key) != 32:
                raise DecryptionError("資料庫金鑰檔格式不正確")
        _cache[cache_key] = key
        return key


def reset_key_cache():
    with _lock:
        _cache.clear()


def _subkey(key, label):
    return hmac.new(key, label, hashlib.sha256).digest()


def _keystream_xor(key, nonce, data):
    out = bytearray()
    for block in range(0, len(data), 32):
        pad = hmac.new(key, nonce + (block // 32).to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(a ^ b for a, b in zip(data[block:block + 32], pad))
    return bytes(out)


def encrypt_text(value, db_path, force_fallback=False):
    if value is None or value == "":
        return value
    if isinstance(value, str) and value.startswith(PREFIX):
        return value
    data = str(value).encode("utf-8")
    key = _master_key(db_path)
    nonce = secrets.token_bytes(12)
    if AESGCM is not None and not force_fallback:
        blob = nonce + AESGCM(key).encrypt(nonce, data, None)
        return PREFIX + "v1:" + base64.b64encode(blob).decode("ascii")
    ct = _keystream_xor(_subkey(key, b"enc"), nonce, data)
    tag = hmac.new(_subkey(key, b"mac"), nonce + ct, hashlib.sha256).digest()
    return PREFIX + "v0:" + base64.b64encode(nonce + ct + tag).decode("ascii")


def decrypt_text(value, db_path):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        version, payload = value[len(PREFIX):].split(":", 1)
        blob = base64.b64decode(payload)
        key = _master_key(db_path)
        nonce = blob[:12]
        if version == "v1":
            if AESGCM is None:
                raise DecryptionError("需要 cryptography 套件才能解密 AES-GCM 欄位")
            return AESGCM(key).decrypt(nonce, blob[12:], None).decode("utf-8")
        if version == "v0":
            ct, tag = blob[12:-32], blob[-32:]
            expected = hmac.new(_subkey(key, b"mac"), nonce + ct, hashlib.sha256).digest()
            if not hmac.compare_digest(tag, expected):
                raise DecryptionError("欄位驗證失敗")
            return _keystream_xor(_subkey(key, b"enc"), nonce, ct).decode("utf-8")
    except DecryptionError:
        raise
    except Exception as exc:
        raise DecryptionError("無法解密資料庫欄位，請確認金鑰") from exc
    raise DecryptionError("不支援的加密版本")
