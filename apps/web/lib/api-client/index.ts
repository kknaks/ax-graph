// FastAPI 호출 클라이언트. Authorization: Bearer <token> (AXKG-SPEC-008).
//
// - base URL: NEXT_PUBLIC_AXKG_API_BASE_URL
// - localStorage token 자동 첨부
// - 보호 API 401 응답 시 token 제거 + /login 리다이렉트 (Case Matrix)

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_AXKG_API_BASE_URL ?? "http://localhost:8000";

const TOKEN_STORAGE_KEY = "axkg_token";

// --- 백엔드 스키마 (apps/api/axkg/schemas/auth.py) ---

/** role은 admin/staff 2값 고정 (AXKG-SPEC-008 §4 Role Model). */
export type UserRole = "admin" | "staff";

export interface ApiUser {
  email: string;
  display_name: string | null;
  /** 내비/가드 분기용 (AXKG-SPEC-008 — login·/auth/me 응답에 포함). */
  role: UserRole;
}

export interface LoginResponse {
  token: string;
  user: ApiUser;
}

export interface MeResponse {
  user: ApiUser;
}

export interface LogoutResponse {
  ok: boolean;
}

// --- 에러 계약: 401 {"detail": {"error_code", "message"}} ---

export class ApiError extends Error {
  constructor(
    public status: number,
    public errorCode: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** AXKG-SPEC-008 Case Matrix — error_code → 프론트 문구 */
export const CASE_MESSAGES: Record<string, string> = {
  INVALID_CREDENTIALS: "이메일 또는 비밀번호가 올바르지 않습니다.",
  INACTIVE_ACCOUNT: "비활성화된 계정입니다. 관리자에게 문의하세요.",
  MISSING_TOKEN: "로그인이 필요합니다.",
  INVALID_TOKEN: "세션이 유효하지 않습니다. 다시 로그인해 주세요.",
  FORBIDDEN: "접근 권한이 없습니다.",
  NETWORK_ERROR: "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
};

export function caseMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return CASE_MESSAGES[error.errorCode] ?? error.message ?? fallback;
  }
  return fallback;
}

// --- token 저장소 (MVP는 localStorage, AXKG-SPEC-008 Token Storage) ---

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

// --- fetch 래퍼 ---

export interface ApiFetchOptions extends RequestInit {
  /** false면 Authorization 헤더를 붙이지 않는다 (예: /auth/login). 기본 true. */
  auth?: boolean;
  /** false면 401에서도 /login 리다이렉트를 하지 않는다 (가드가 직접 처리할 때). 기본 true. */
  redirectOn401?: boolean;
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { auth = true, redirectOn401 = true, ...init } = options;

  const headers = new Headers(init.headers);
  // FormData(멀티파트 업로드)는 브라우저가 boundary 포함 Content-Type을 직접 설정해야 하므로 건드리지 않는다.
  if (
    init.body != null &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", CASE_MESSAGES.NETWORK_ERROR);
  }

  if (!res.ok) {
    let errorCode = "UNKNOWN_ERROR";
    let message = `요청에 실패했습니다. (${res.status})`;
    try {
      const body = (await res.json()) as {
        detail?: { error_code?: string; message?: string } | string;
      };
      if (typeof body.detail === "object" && body.detail?.error_code) {
        errorCode = body.detail.error_code;
        message = body.detail.message ?? message;
      }
    } catch {
      // body가 JSON이 아니면 기본 메시지 유지
    }

    if (res.status === 401 && redirectOn401 && typeof window !== "undefined") {
      clearToken();
      if (!window.location.pathname.startsWith("/login")) {
        const reason = errorCode === "MISSING_TOKEN" ? "missing_token" : "invalid_token";
        window.location.href = `/login?reason=${reason}`;
      }
    }
    throw new ApiError(res.status, errorCode, message);
  }

  return (await res.json()) as T;
}

// --- auth API (AXKG-SPEC-008 API Contract) ---

export function login(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    auth: false,
    redirectOn401: false, // 401 = INVALID_CREDENTIALS → 로그인 페이지가 직접 표시
  });
}

export function me(options: ApiFetchOptions = {}): Promise<MeResponse> {
  return apiFetch<MeResponse>("/auth/me", options);
}

/** 서버 token revoke 후 로컬 token 삭제. 서버 호출이 실패해도 로컬 token은 지운다. */
export async function logout(): Promise<void> {
  try {
    await apiFetch<LogoutResponse>("/auth/logout", {
      method: "POST",
      redirectOn401: false,
    });
  } catch {
    // 이미 무효한 token이어도 클라이언트 로그아웃은 진행한다.
  } finally {
    clearToken();
  }
}
