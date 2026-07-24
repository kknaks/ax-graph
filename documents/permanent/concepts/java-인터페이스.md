---
type: concept
title: "Java 인터페이스(Interface)"
aliases: ["Java interface", "인터페이스", "implements 키워드"]
tags: ["Java", "OOP", "인터페이스", "다중상속", "다형성", "마커인터페이스"]
up: []
---

# Java 인터페이스(Interface)

## 정의

Java에서 구현 객체들이 동일한 동작을 수행함을 보장하기 위해 설계된 순수 추상 타입; 상속 계층과 무관하게 클래스들을 자유롭게 타입으로 묶고 다중 구현을 허용한다.

## 맥락

내부 모든 메서드는 기본적으로 `public abstract`, 모든 필드는 `public static final` 상수다(default·static·private 메서드 예외). `implements` 키워드로 사용하며 클래스에 다중 구현이 가능하고, 인터페이스끼리도 다중 상속을 지원한다.

핵심 사용 목적은 **자유로운 타입 묶음**이다. `extends`(상속)가 논리적 계층 관계로 타입을 묶는 것과 달리, `implements`(구현)는 상속 관계와 무관하게 논리적으로 관련 없는 클래스들도 형제 타입처럼 묶는다. 예: `Swimmable` 인터페이스를 People과 Whale이 구현하면, Animal 계층에서 위치가 달라도 Swimmable 타입으로 취급된다. 인터페이스 타입을 중개 타입(예: `Storable target` 필드)으로 활용하면 전혀 다른 클래스들을 동일 타입으로 처리할 수 있다. 네이밍 관례는 `xxxable` 형식이다.

**마커 인터페이스**: 아무 메소드도 선언하지 않는 빈 껍데기 인터페이스. 객체의 타입 정보만 제공하여 `instanceof` 연산자 기반 타입 구분 코드를 단순화한다. Java 표준 라이브러리의 `Serializable`·`Cloneable`이 대표 사례다.

## 근거 출처

- [[java-인터페이스-vs-추상클래스-용도-차이점]] — 인터페이스 정의·다중 구현·마커 인터페이스·자유로운 타입 묶음·인터페이스 다형성 설계 설명 출처
