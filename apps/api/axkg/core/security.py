"""토큰 발급/검증 (AXKG-SPEC-008). token은 hash로만 저장한다. WP0 Phase 4.

- password: PBKDF2-SHA256 (stdlib, 외부 의존성 없음 — MVP seed 계정 기준).
- token: `secrets.token_urlsafe` 발급, DB에는 SHA-256 hex hash만 저장.
- Bearer 검증 dependency: auth 외 모든 라우터에 기본 적용.
  제외: `/health`, `/integrations/slack/*` (Slack signing secret 검증 소관, AXKG-SPEC-003).
- 에러 계약은 AXKG-SPEC-008 Case Matrix (MISSING_TOKEN / INVALID_TOKEN).
"""
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from axkg.core.database import get_session
from axkg.dto.auth import AuthContextDTO, UserDTO

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != PBKDF2_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _unauthorized(error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail={"error_code": error_code, "message": message}
    )


async def get_current_auth(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AuthContextDTO:
    """Authorization: Bearer <token> 검증 dependency.

    services import는 런타임에 수행한다(core → services 모듈 순환 회피;
    검증 로직 자체는 AuthService에 위임).
    """
    from axkg.services.auth import AuthService

    header = request.headers.get("Authorization")
    if header is None or not header.startswith("Bearer "):
        raise _unauthorized("MISSING_TOKEN", "Authorization header 없음")
    token = header.removeprefix("Bearer ").strip()
    if not token:
        raise _unauthorized("MISSING_TOKEN", "Authorization header 없음")

    user = await AuthService(session).resolve_token(token)
    if user is None:
        raise _unauthorized("INVALID_TOKEN", "token 검증 실패")
    return AuthContextDTO(user=user, token=token)


async def get_current_user(auth: AuthContextDTO = Depends(get_current_auth)) -> UserDTO:
    return auth.user


async def require_admin(user: UserDTO = Depends(get_current_user)) -> UserDTO:
    """admin 전용 라우트 가드 (AXKG-SPEC-008 Access Boundary Matrix).

    role이 admin이 아니면 `FORBIDDEN`(403). FE 가드는 UX이고 이 가드가 실제 방어선이다.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"error_code": "FORBIDDEN", "message": "접근 권한이 없습니다."},
        )
    return user
