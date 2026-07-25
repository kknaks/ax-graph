---
type: concept
title: "음성 인식 STT(Speech-to-Text)"
aliases: ["STT", "Speech-to-Text", "음성인식", "자동 음성 인식", "ASR"]
tags: ["STT", "음성인식", "ASR", "회의전사"]
up: []
---

# 음성 인식 STT(Speech-to-Text)

## 정의

오디오 스트림 또는 파일에서 사람의 발화를 인식해 텍스트로 변환하는 기술. ASR(Automatic Speech Recognition)이라고도 한다.

## 맥락

STT는 실행 위치와 처리 방식에 따라 크게 두 범주로 나뉜다.

**실시간(스트리밍) 방식**: 오디오를 청크 단위로 연속 전송하며 부분 전사(partial)와 확정 전사(committed)를 실시간으로 반환한다. [[음성활동감지-vad]]가 발화 구간을 감지해 언제 문장을 확정할지 결정한다. ElevenLabs Scribe의 `scribe_v2_realtime`(WebSocket), Google Cloud STT 스트리밍 API, Web Speech API가 이 범주에 속한다.

**배치(파일) 방식**: 녹음이 완료된 오디오 파일을 통째로 전송해 전체 전사 결과를 한 번에 받는다. 처리 시간은 오래 걸리지만 화자분리(diarization)·단어 타임스탬프 등 후처리 품질이 높다. ElevenLabs Scribe의 `scribe_v2`(REST), Google Cloud STT Long Running 방식이 이 범주다.

**vendor 선택 기준**: 회의 전사처럼 화자 분리·단어 타임스탬프·VOD 재전사가 필요한 경우 서버 기반 유료 STT(ElevenLabs, Google Cloud)가 필요하다. 단순 실시간 받아쓰기라면 브라우저 내장 무료 Web Speech API로 충분하다. VAD 세밀 제어가 중요하면 ElevenLabs가 유리(3종 노브), 도메인 적응·화자 수 힌트·모델 선택이 필요하면 Google Cloud STT가 우위다.

## 근거 출처

- [[elevenlabs-scribe-stt-설정-파라미터-레퍼런스]] — ElevenLabs Scribe Realtime/Batch 두 경로와 Web Speech API·Google Cloud STT 3자 비교의 원문 출처
