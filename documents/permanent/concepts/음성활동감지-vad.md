---
type: concept
title: "음성활동감지 VAD(Voice Activity Detection)"
aliases: ["VAD", "Voice Activity Detection", "발화 구간 감지", "음성활동 감지"]
tags: ["STT", "VAD", "음성인식", "발화구간", "ElevenLabs-Scribe"]
up: ["음성-인식-stt"]
---

# 음성활동감지 VAD(Voice Activity Detection)

## 정의

오디오 스트림에서 사람의 발화가 시작·진행·종료되는 구간을 실시간으로 판별해 [[음성-인식-stt]] 엔진에 발화 확정 타이밍을 알려주는 기술.

## 맥락

VAD는 실시간 STT에서 "언제 문장이 끝났는가"를 결정하는 핵심 로직이다. 발화 경계를 잘못 감지하면 자막이 지나치게 잘게 끊기거나, 한 덩이로 뭉쳐 늦게 나오거나, 짧은 환경 소음·감탄사가 발화로 오인된다.

ElevenLabs Scribe Realtime 경로(`commit_strategy=vad`)는 세 가지 VAD 노브를 URL 쿼리스트링으로 노출한다:

| 파라미터 | 기본값 | 역할 |
|---|---|---|
| `vad_silence_threshold_secs` | `0.7` | 이 시간(초)만큼 침묵이 지속되면 발화 끝으로 판정·확정. ↓=자막이 빠르고 잘게 끊김, ↑=문장을 길게 묶어 반환 |
| `vad_threshold` | `0.4` | 음성/비음성 판정 민감도(0~1). ↓=원거리·약한 발화도 인식(잡음도 증가), ↑=근거리·강한 발화만 인식 |
| `min_speech_duration_ms` | `250` | 이보다 짧은 소리는 발화로 처리하지 않음. "네"/"아니" 같은 짧은 환각 자막 차단에 유효 |

세 노브의 트레이드오프:
- 자막이 늦거나 한 덩이로 나온다 → `vad_silence_threshold_secs` ↓
- 짧은 환각 자막이 반복된다 → `min_speech_duration_ms` ↑, `vad_threshold` ↑
- 원거리 발화자 자막이 누락된다 → `vad_threshold` ↓

Google Cloud STT 스트리밍 경로는 `speechEndTimeout`·`speechStartTimeout` 2종으로 VAD 타이밍을 제어한다. ElevenLabs는 노브 3개로 더 세밀하다. Web Speech API는 VAD 제어를 브라우저 엔진 내부에 위임해 외부에서 조정 불가능하다.

## 근거 출처

- [[elevenlabs-scribe-stt-설정-파라미터-레퍼런스]] — ElevenLabs Scribe Realtime 경로 VAD 3종 노브 파라미터·기본값·조정 권장의 원문 출처
