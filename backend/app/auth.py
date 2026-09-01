"""认证模块：RSA 密钥对、密码哈希、Token 签发与校验。

设计要点：
- 前端在 HTTP 明文环境下调用登录接口，密码用 RSA(PKCS1 v1.5) 加密后传输，
  避免口令以明文在网络上暴露（部署为 HTTP，非 HTTPS）。
- 后端进程内生成 RSA-2048 密钥对与 Token 密钥，重启即轮换。
- 用户口令仅以 pbkdf2 哈希保存在内存中，不落盘、不写日志。
- Token 为 HMAC-SHA256 签名的自包含令牌，有效期 24 小时。
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# ---- RSA 密钥对（进程内生成，重启即轮换）----
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_PEM = _PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode("utf-8")

# ---- Token 密钥与有效期（进程内生成）----
_TOKEN_SECRET = os.urandom(32)
TOKEN_EXPIRE_SECONDS = 24 * 3600

# ---- 用户表 ----
# 默认预置两个用户；可通过环境变量 PREMIUM_USERS 覆盖（格式：user:pass,user:pass）。
def _load_users() -> dict:
    raw = os.environ.get("PREMIUM_USERS")
    users: dict = {}
    if raw:
        for pair in raw.split(","):
            if ":" in pair:
                u, p = pair.split(":", 1)
                users[u.strip()] = p
    else:
        users["18621395576"] = "LsJ123456"
        users["18616852546"] = "LsJ123456"
    return users

_USERS = _load_users()

_PBKDF2_SALT = os.urandom(16)
_PBKDF2_ITERS = 100_000
# 预计算存储哈希，避免每次登录重复计算
_USER_HASHES = {
    u: hashlib.pbkdf2_hmac("sha256", p.encode("utf-8"), _PBKDF2_SALT, _PBKDF2_ITERS).hex()
    for u, p in _USERS.items()
}


def get_public_key_pem() -> str:
    """返回 PEM 格式 RSA 公钥，供前端加密密码。"""
    return _PUBLIC_PEM


def decrypt_password(enc_b64: str) -> Optional[str]:
    """RSA(PKCS1 v1.5) 解密前端传来的密码密文（base64）。失败返回 None。"""
    try:
        ciphertext = base64.b64decode(enc_b64)
        plaintext = _PRIVATE_KEY.decrypt(ciphertext, padding.PKCS1v15())
        return plaintext.decode("utf-8")
    except Exception:
        return None


def verify_credentials(username: str, password: str) -> bool:
    """校验用户名 + 明文密码（常量时间比较）。"""
    stored = _USER_HASHES.get(username)
    if not stored:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), _PBKDF2_SALT, _PBKDF2_ITERS
    ).hex()
    return hmac.compare_digest(stored, candidate)


def make_token(username: str) -> str:
    """为指定用户签发 24h Token（body.sign）。"""
    payload = {"u": username, "exp": int(time.time()) + TOKEN_EXPIRE_SECONDS}
    body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
        .decode("utf-8")
        .rstrip("=")
    )
    sig = hmac.new(_TOKEN_SECRET, body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> Optional[str]:
    """校验 Token 签名与有效期，返回用户名；无效/过期返回 None。"""
    if not token:
        return None
    try:
        body, sig = token.rsplit(".", 1)
        expect = hmac.new(_TOKEN_SECRET, body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload.get("u")
    except Exception:
        return None
