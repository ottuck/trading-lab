"""Cloudflare Access 확인 (N7, project.md 6절).

도메인 접속은 Cloudflare Tunnel → Access(본인 이메일만) 뒤에 둔다. Access가 이미 막지만,
정책 설정 실수로 열리는 일을 막으려고 API도 Access 토큰(JWT)을 한 번 더 확인한다.
Cloudflare를 거쳐 온 요청(cf-ray 헤더)만 확인하고, Tailscale로 온 요청은 그대로 둔다.
"""

import jwt
from jwt import PyJWKClient


class AccessGuard:
    def __init__(self, team: str, aud: str) -> None:
        self.issuer = f"https://{team}.cloudflareaccess.com"
        self.aud = aud
        # 서명 키는 Cloudflare가 돌려가며 바꾸므로 공개 키 목록에서 읽고 한 시간 동안 기억한다.
        self.jwks = PyJWKClient(f"{self.issuer}/cdn-cgi/access/certs", lifespan=3600)

    def allows(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            jwt.decode(token, key.key, algorithms=["RS256"], audience=self.aud, issuer=self.issuer)
        except jwt.PyJWTError:
            return False
        return True
