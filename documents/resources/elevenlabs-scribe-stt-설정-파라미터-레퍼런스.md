---
type: reference
title: "ElevenLabs Scribe STT 설정·파라미터 레퍼런스 (Realtime/Batch) 및 Web Speech·Google Cloud STT 비교"
source: ""
aliases: ["ElevenLabs Scribe 파라미터", "Scribe STT 레퍼런스", "scribe_v2 설정", "ElevenLabs 회의 전사 설정"]
tags: ["STT", "ElevenLabs-Scribe", "음성인식", "회의전사", "화자분리", "VAD", "WebSocket", "배치전사", "Web-Speech-API", "Google-Cloud-STT"]
up: []
---

# ElevenLabs Scribe STT 설정·파라미터 레퍼런스 (Realtime/Batch) 및 Web Speech·Google Cloud STT 비교

## 요약

ElevenLabs Scribe [[음성-인식-stt]]를 회의 전사에 적용할 때 필요한 Realtime(WebSocket)·Batch(REST) 두 경로의 파라미터 전체와 env 설정을 정리한 레퍼런스 문서다. Web Speech API·Google Cloud STT와의 기능 대응표 및 미세조정 우선순위도 포함한다.

## 핵심 내용

### 경로 개요

두 경로는 프로토콜·모델·파라미터 전달 방식이 완전히 분리된다.

| 경로 | 프로토콜 | 모델 | 사용 시점 | 파라미터 전달 |
|---|---|---|---|---|
| **Realtime** | WebSocket | `scribe_v2_realtime` | 회의 중 실시간 | URL 쿼리스트링 |
| **Batch** | REST (multipart) | `scribe_v2` | 회의 종료 시 | multipart form data |

### 공통 기본 설정 (env)

| env | 기본값 | 역할 |
|---|---|---|
| `STT_VENDOR` | `mock` | `mock`(가짜 자막) / `elevenlabs`(실 vendor) 토글 |
| `ELEVENLABS_API_KEY` | `""` | 인증키. `xi-api-key` 헤더로 전달. realtime·batch 공용 |
| `ELEVENLABS_WS_URL` | 조립 URL | realtime WS 엔드포인트+파라미터. 언어·VAD 튜닝 진입점 |
| `ELEVENLABS_BATCH_STT_URL` | `https://api.elevenlabs.io/v1/speech-to-text` | batch REST 엔드포인트 |

인증은 모든 호출에 `xi-api-key: {API_KEY}` 헤더 하나로 양쪽 공용이다. 오디오 원본 포맷은 16kHz · mono · 16-bit LE PCM이며, `make_stt_client()` factory가 `STT_VENDOR` 값을 보고 `MockSTTClient` / `ElevenLabsSTTClient`를 선택한다.

실 vendor 최소 설정:
```bash
STT_VENDOR=elevenlabs
ELEVENLABS_API_KEY=sk_...  # ElevenLabs 대시보드 > Profile > API Keys
```

### Realtime 파라미터 (WebSocket)

파라미터 전부 **WS URL 쿼리스트링**으로 전달된다(`config.py:66` 기본 조립값):

```
wss://api.elevenlabs.io/v1/speech-to-text/realtime
  ?model_id=scribe_v2_realtime
  &language_code=ko
  &audio_format=pcm_16000
  &commit_strategy=vad
  &vad_silence_threshold_secs=0.7
  &vad_threshold=0.4
  &min_speech_duration_ms=250
  &include_timestamps=true
```

| 파라미터 | 기본값 | 역할 |
|---|---|---|
| `model_id` | `scribe_v2_realtime` | realtime 전용 모델 |
| `language_code` | `ko` | 인식 언어 고정 (ISO 639). 다국어 대응 시 §언어 설정 참고 |
| `audio_format` | `pcm_16000` | 입력 오디오 포맷. realtime은 `sample_rate` 쿼리 미지원 → 이걸로 대체 |
| `commit_strategy` | `vad` | 발화 확정 전략. `vad`=[[음성활동감지-vad]]로 자동 확정 |
| `vad_silence_threshold_secs` | `0.7` | 이 시간만큼 침묵하면 발화 끝으로 판정·확정. ↓=자막 빠르고 잘게 끊김, ↑=길게 묶임 |
| `vad_threshold` | `0.4` | 음성/비음성 판정 민감도. ↓=원거리 발화도 인식(잡음 증가), ↑=근거리 강한 발화만 |
| `min_speech_duration_ms` | `250` | 이보다 짧은 소리는 발화로 미처리. 공용 마이크 환각("네"/"아니") 차단 |
| `include_timestamps` | `true` | committed 메시지에 단어별 `[text, start, end]` 부착. 화자 단어분할의 전제 |

[[음성활동감지-vad]] 3종 노브(`vad_silence_threshold_secs`, `vad_threshold`, `min_speech_duration_ms`)가 실시간 발화 구간 제어의 핵심이다. Web Speech API에는 이 제어가 없다.

#### 연결·오디오 송신 규약

- **인증**: `additional_headers={"xi-api-key": key}`로 WS connect.
- **ack 대기**: 연결 직후 `{"message_type":"session_started"}` 수신 후 오디오 송신 시작. 먼저 보내면 reject.
- **오디오 프레임**: raw PCM을 binary로 보내면 `1008 invalid_request`. 반드시 base64 인코딩 후 text frame:
  ```json
  {"message_type":"input_audio_chunk","audio_base_64":"<base64 PCM>"}
  ```

#### 수신 메시지 타입

| message_type | 의미 |
|---|---|
| `session_started` | 연결 ack |
| `partial_transcript` | 진행 중 추정 자막 (`text`) |
| `committed_transcript` | 확정 자막 (text only) |
| `committed_transcript_with_timestamps` | 확정 자막 + `words[]` |
| `*error*` | auth_error / quota_exceeded / rate_limited / insufficient_audio_activity 등 |

`include_timestamps=true` 시 한 발화에 text-only + with_timestamps **두 메시지**가 온다. `with_timestamps`를 정본으로 사용하고 text-only는 skip한다.

### Batch 파라미터 (REST)

회의 종료 시 녹음 wav를 통째로 재전사해 화자분리(`speaker_id`)를 얻고 라이브 라벨을 교체하는 1-shot REST 호출이다.

#### 요청 파라미터 (multipart form)

```
POST https://api.elevenlabs.io/v1/speech-to-text
헤더: xi-api-key: {key}
form:
  file                   = meeting.wav (audio/wav)
  model_id               = scribe_v2
  diarize                = true
  timestamps_granularity = word
  language_code          = ko
```

| 파라미터 | 기본값 | 역할 |
|---|---|---|
| `file` | — | 전사할 오디오(wav). 경로/bytes 허용 |
| `model_id` | `scribe_v2` | 배치 모델 (realtime `scribe_v2_realtime`과 다름) |
| `diarize` | `true` | 화자분리 ON. 단어별 `speaker_id` 부여 |
| `timestamps_granularity` | `word` | 타임스탬프 단위. `word`=단어별 start/end |
| `language_code` | `ko` | 인식 언어 고정. finalize에서 인자를 안 넘겨 기본 ko 적용 |

코드 레벨 옵션: `timeout=300.0`, `max_retries=2`(5xx·타임아웃 지수 backoff, 4xx 즉시 실패), `backoff_base=1.0`.

#### 응답 필드

| 필드 | 의미 |
|---|---|
| `text` | 전체 전사 텍스트 |
| `words[]` | `{text, start, end, type, speaker_id, logprob}`. `type=spacing`은 공백(단어 목록 제외) |
| `language_code` | 감지·사용된 언어 |
| `language_probability` | 언어 감지 확신도 |
| `audio_duration_secs` | 오디오 길이 |
| `transcription_id` | vendor 전사 ID |

단어 0건이면 `BatchSTTError` → 호출부(finalize)가 라이브 라벨 유지 fallback.

### Realtime ↔ Batch 파라미터 대응 요약

| 개념 | Realtime | Batch |
|---|---|---|
| 모델 | `scribe_v2_realtime` | `scribe_v2` |
| 언어 | `language_code` (URL) | `language_code` (form) |
| 오디오 | `audio_format=pcm_16000` + base64 스트림 | `file` (wav 파일 통째) |
| 발화 구간 | `commit_strategy=vad` + [[음성활동감지-vad]] 3종 | 없음 (파일 전체 처리) |
| 타임스탬프 | `include_timestamps=true` | `timestamps_granularity=word` |
| 화자분리 | ✗ (realtime 미지원) | ✓ `diarize=true` |
| 인증 | `xi-api-key` 헤더 | `xi-api-key` 헤더 |

### 언어 설정 — 한국어 고정 원인과 해결

`language_code=ko`가 두 군데 하드코딩되어 있다.
1. **Realtime**: `config.py:69` WS URL 조립에 `&language_code=ko`.
2. **Batch**: `transcribe_batch(..., language_code="ko")` 기본값 + finalize가 인자를 미전달.

해결 방안 세 가지:

- **(A) env override (realtime, 코드 변경 없음)**: `ELEVENLABS_WS_URL` 전체를 원하는 `language_code=en`으로 교체. 단, 전역 1개 언어만 가능하고 batch는 여전히 ko.
- **(B) auto-detect (코드 소량)**: `language_code` 생략 → 자동 감지(응답 `language_probability`). batch는 확실, realtime 생략 지원은 vendor 확인 필요.
- **(C) 회의별 언어 (정공법)**: 회의 생성 시 언어 입력받아 realtime URL 동적 조립 + `transcribe_batch(language_code=회의언어)`. 다국어 회의 대응 가능.

> ⚠️ 어느 방법이든 **realtime + batch 둘 다** 수정해야 한다. batch만 안 바꾸면 종료 후 화자분리 재전사에서 다시 한국어로 깨진다.

### Web Speech API vs ElevenLabs 비교

[[음성-인식-stt]] vendor 선택 맥락에서, Web Speech API와 ElevenLabs의 근본 차이는 실행 위치다.

| | Web Speech API | ElevenLabs Scribe |
|---|---|---|
| 실행 위치 | 브라우저 (프론트) | 서버 (백엔드가 WS/REST 호출) |
| 오디오 흐름 | 브라우저 → 구글 서버 | 브라우저 → 백엔드 → ElevenLabs |
| API 키 | 불필요 | 필요 (`xi-api-key`) + 과금 |
| 브라우저 의존 | Chrome 계열만 안정 (Firefox ✗) | 무관 (서버 처리) |

#### 기능 대응표

| 기능 | Web Speech API | ElevenLabs |
|---|---|---|
| 실시간 마이크 전사 | ✓ | ✓ (realtime WS) |
| **VOD(녹화 파일) 전사** | ✗ | ✓ (batch, wav 통째) |
| **단어별 타임스탬프** | ✗ | ✓ |
| **화자분리** | ✗ | ✓ (batch `diarize=true`) |
| **[[음성활동감지-vad]] 제어** | ✗ (엔진 내부) | ✓ (3종 노브) |
| 중간 결과 | ✓ `interimResults` | ✓ `partial_transcript` |
| 대안 후보 N개 | ✓ `maxAlternatives` | ✗ |
| 문구 보정(bias) | ✓ `phrases` | ✗ |

#### 개념 매핑

| 하고 싶은 것 | Web Speech API | ElevenLabs |
|---|---|---|
| 인식 언어 | `lang='ko-KR'` | `language_code=ko` |
| 중간 자막 | `interimResults=true` | `partial_transcript` 메시지 |
| N초 침묵 시 문장 끝 | **불가** | `vad_silence_threshold_secs` |
| 발화 최소 길이 | 불가 | `min_speech_duration_ms` |
| 화자 나누기 | 불가 | batch `diarize=true` |
| 녹화파일 전사 | 불가 | batch REST |

**한 줄 정리**: 실시간 마이크 자막만 필요하면 Web Speech API, 화자 나뉜 회의록 + 종료 후 정밀 전사가 필요하면 ElevenLabs(adr-08 채택 근거). 둘은 대체재가 아니라 급이 다르다.

### Google Cloud STT 비교 참고

#### 3자 비교

| 축 | Web Speech | **ElevenLabs** | Google Cloud STT |
|---|---|---|---|
| 실행·과금 | 브라우저·무료·키X | 서버·유료·키O | 서버·유료·키O |
| VAD 제어 | ✗ | **`vad_*` 3종** | `speechStart/EndTimeout` 2종 |
| 화자분리 | ✗ | `diarize=true` (수 힌트 없음) | `diarizationConfig`(min/max 힌트 O) |
| 도메인 용어 보정 | `phrases` | **✗** | `adaptation`+`boost` (강력) |
| 모델 선택 | ✗ | `scribe_v2` 계열 단일 | video/phone/medical/long 등 다양 |
| 단어 타임스탬프 | ✗ | ✓ | ✓ |
| 자동 문장부호 | △ | ✗ | ✓ |

**핵심 차이**: Google은 도메인 적응·모델 선택·metadata 노브가 많다. ElevenLabs는 설정이 단순한 대신 이 노브들이 없다. [[음성활동감지-vad]]는 ElevenLabs가 더 세밀(3개 vs Google 2개). 화자 수 힌트는 Google만 지원.

#### 미세조정 우선순위

| 순위 | 파라미터 | ElevenLabs | Google | 왜 중요한가 |
|---|---|---|---|---|
| ① | VAD 침묵 임계 | `vad_silence_threshold_secs` (0.7) | `speechEndTimeout` | 발화 확정 타이밍. 끊김/지연의 핵심 노브 |
| ② | VAD 민감도·최소발화 | `vad_threshold`(0.4)·`min_speech_duration_ms`(250) | VAD 이벤트 | 환각 억제 ↔ 원거리 발화자 누락 트레이드오프 |
| ③ | 도메인 용어 보정 | **없음** | `adaptation.phrases`+`boost` | 의료용어·제품명 인식률. ElevenLabs 한계 항목 |
| ④ | 모델 선택 | `scribe_v2` 고정 | `model`+`useEnhanced` | 오디오 성격에 맞는 음향 모델 → 정확도 근본 향상 |
| ⑤ | 화자 수 힌트 | **없음** | `min/maxSpeakerCount` | 화자 오분할·병합 감소. ElevenLabs 한계 항목 |
| ⑥ | 언어(다국어) | `language_code` / 생략=auto | `alternativeLanguageCodes` | 언어 고정 하드코딩 문제 직결 |

**실전 권장**: 지금 당장 ElevenLabs에서 조정 가능한 것은 VAD(①②)와 언어(⑥)뿐. 도메인 용어(③)·모델(④)·화자 수 힌트(⑤)가 필요하면 ElevenLabs로는 한계 → Google Cloud STT 전환 검토.

### 트러블슈팅

| 증상 | 확인 사항 |
|---|---|
| 다른 언어가 한국어로 깨짐 | `language_code=ko` 하드코딩 (§언어 설정) |
| 자막 아예 안 나옴 | `STT_VENDOR=elevenlabs` / `ELEVENLABS_API_KEY` 설정 여부 |
| `1008 invalid_request` | 오디오를 base64 JSON이 아닌 binary로 전송 |
| 연결 직후 끊김 | `session_started` ack 전에 오디오 송신 |
| 단어 offset 0건 / 화자분할 안 됨 | realtime `include_timestamps=true` 누락 |
| 환각 자막 반복("네"/"아니") | `min_speech_duration_ms`↑, `vad_threshold`↑ |
| `quota_exceeded`/`rate_limited` | vendor 플랜 한도 — error 로그 확인 |
| 종료 후 화자분리 이상 | batch `diarize=true`/`granularity=word`/wav 포맷 |

### 참고 구현 파일

- `meeting_stt_client.py` — 클라이언트·파서
- `config.py:58~82` — 파라미터 기본값
- `meeting_v2_finalize.py` — batch 호출부
- `.env.example` — env 토글 예시

## 연결

- [[음성-인식-stt]] — 이 문서가 다루는 ElevenLabs Scribe가 속하는 STT 기술 범주 SoT 위임
- [[음성활동감지-vad]] — Realtime 경로 발화 구간 제어 핵심 개념(VAD 3종 노브) SoT 위임
