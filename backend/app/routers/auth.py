"""认证路由：RSA 公钥下发、登录、登出。

路径前缀已在本文件内设置为 /api/auth，main.py 引入时不再叠加 /api。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginReq(BaseModel):
    username: str
    # RSA(PKCS1 v1.5) 加密后的密码，base64 编码
    enc: str


@router.get("/rsa-public-key")
def rsa_public_key():
    """下发 RSA 公钥，供前端加密登录密码。"""
    return {"public_key": auth.get_public_key_pem()}


@router.post("/login")
def login(req: LoginReq):
    """校验用户名 + 解密后的密码，成功返回 24h Token。"""
    password = auth.decrypt_password(req.enc)
    if password is None or not auth.verify_credentials(req.username, password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = auth.make_token(req.username)
    return {
        "token": token,
        "token_type": "Bearer",
        "expires_in": auth.TOKEN_EXPIRE_SECONDS,
        "username": req.username,
    }


@router.post("/logout")
def logout():
    """登出：服务端无状态，客户端清除 Token 即可。"""
    return {"success": True}
