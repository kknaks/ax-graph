"""PLAN-010-T-008 — is_resume_session 판정 단위 테스트.

글로벌 설정에서 스냅샷된 bare `resume=True`를 실제 세션 resume dict와 구분한다. 이 판정이
세 context builder(source_summary·classification_gate·documentation_gate)의 feedback-only
분기 게이트다 — bare true를 실세션으로 오인하면 컨텍스트 없는 재생성이 된다.
"""
from axkg.services.ai.resolution import is_resume_session


def test_bare_true_is_not_resume_session() -> None:
    # 글로벌 options.resume=True가 스냅샷된 경우 — executor는 --resume하지 않는다(새 세션).
    assert is_resume_session({"resume": True}) is False


def test_false_none_and_missing_are_not_resume_session() -> None:
    assert is_resume_session({"resume": False}) is False
    assert is_resume_session({"resume": None}) is False
    assert is_resume_session({}) is False
    assert is_resume_session(None) is False


def test_session_dict_is_resume_session() -> None:
    assert (
        is_resume_session({"resume": {"mode": "session", "session_id": "sess-1"}})
        is True
    )


def test_malformed_resume_dict_is_not_resume_session() -> None:
    # session_id 없음 / 빈 값 / 다른 mode / mode 없음 — 전부 실세션 아님.
    assert is_resume_session({"resume": {"mode": "session"}}) is False
    assert is_resume_session({"resume": {"mode": "session", "session_id": ""}}) is False
    assert is_resume_session({"resume": {"mode": "fresh", "session_id": "s1"}}) is False
    assert is_resume_session({"resume": {"session_id": "s1"}}) is False
