---
type: summary
title: Java 인터페이스 vs 추상클래스 용도 차이점 완벽 이해
source_url: https://inpa.tistory.com/entry/JAVA-%E2%98%95-%EC%9D%B8%ED%84%B0%ED%8E%98%EC%9D%B4%EC%8A%A4-vs-%EC%B6%94%EC%83%81%ED%81%B4%EB%9E%98%EC%8A%A4-%EC%B0%A8%EC%9D%B4%EC%A0%90-%EC%99%84%EB%B2%BD-%EC%9D%B4%ED%95%B4%ED%95%98%EA%B8%B0
tags:
- 인터페이스
- 추상클래스
- Java
- OOP
- 다형성
- 다중상속
- 마커인터페이스
- 디자인패턴
- 추상화
- 상속
summarized_at: '2026-07-21T01:25:24.119455+00:00'
---

## 인터페이스 vs 추상클래스 비교표

| 구분 | 추상 클래스 | 인터페이스 |
|------|------------|------------|
| 키워드 | `abstract` | `interface` |
| 사용 가능 변수 | 제한 없음 | `static final` (상수)만 |
| 접근 제어자 | 제한 없음 | `public`만 |
| 사용 가능 메소드 | 제한 없음 | abstract, default, static, private |
| 상속 키워드 | `extends` | `implements` |
| 다중 상속 | 불가능 | 가능 (다중 구현 + 인터페이스 간 다중 상속) |

## 공통점

1. 추상 메소드를 가지고 있어야 한다.
2. 인스턴스화 불가 (`new` 생성자 사용 불가)
3. 구현체의 인스턴스를 통해 사용해야 한다.
4. 상속/구현한 클래스는 추상 메소드를 반드시 구현해야 한다.

## 인터페이스 정리

- 내부 모든 메서드는 `public abstract`로 정의 (default 메소드 제외)
- 내부 모든 필드는 `public static final` 상수
- 클래스에 **다중 구현** 지원, 인터페이스끼리 **다중 상속** 지원
- `static`, `default`, `private` 메서드로 구체적인 메서드 보유 가능 → 하위 멤버 중복 메서드 통합 가능하나, 필드는 상수이므로 중복 필드 통합 불가
- 부모-자식 상속 관계에 얽매이지 않고 **자유롭게 붙였다 떼었다** 사용
- **구현 객체가 같은 동작을 한다는 것을 보장**하기 위해 사용하는 것에 초점
- 빈 껍데기 **마커 인터페이스**로도 활용 가능
- 네이밍 규칙: 보통 `xxxable` 형식

## 추상클래스 정리

- 하위 클래스들의 공통점을 모아 추상화하여 만든 클래스
- **단일 상속**만 허용 (다중 상속 불가)
- 추상 메소드 외에 일반 필드, 메서드, 생성자를 가질 수 있음
- **추상화하면서 중복되는 클래스 멤버들을 통합 및 확장** 가능
- **클래스 간의 연관 관계를 구축**하는 것에 초점

## 인터페이스 vs 추상클래스 사용처

핵심은 기능 차이가 아니라 **사용 목적의 차이**다.

- **인터페이스**: `implements` 키워드처럼, 인터페이스에 정의된 메서드를 각 클래스의 목적에 맞게 기능을 구현하는 느낌
- **추상 클래스**: `extends` 키워드처럼, 자신의 기능들을 하위 클래스로 확장시키는 느낌

## 추상클래스를 사용하는 경우

- 상속받을 클래스들이 공통으로 가지는 메소드와 필드가 많아 **중복 멤버 통합**이 필요할 때
- 멤버에 `public` 이외의 접근자(`protected`, `private`) 선언이 필요한 경우
- `non-static`, `non-final` 필드 선언이 필요한 경우 (인스턴스별 상태 변경)
- 요구사항과 함께 구현 세부 정보의 일부 기능만 지정했을 때
- 하위 클래스가 오버라이드하여 재정의하는 기능들을 공유하기 위한 상속 개념을 사용할 때

### 중복 멤버 통합 예시

```java
// 중복 제거 전
class NewlecExam {
    int kor; int eng; int math; // 중복
    void total(){} void avg(){} // 중복
    int com;
}
class YBMExam {
    int kor; int eng; int math; // 중복
    void total(){} void avg(){} // 중복
    int toeic;
}

// 추상클래스로 통합
abstract class Exam {
    int kor; int eng; int math;
    abstract void total();
    abstract void avg();
}
class NewlecExam extends Exam { int com; void total(){} void avg(){} }
class YBMExam extends Exam { int toeic; void total(){} void avg(){} }
```

### 추상클래스의 다형성 이용 설계

- 추상클래스는 클라이언트에서 자료형을 사용하기 전에 **미리 논리적인 클래스 상속 구조를 만들어 놓고 사용이 결정**되는 느낌
- 클라이언트와 추상화 객체들은 **의미적으로 관계로 묶여** 있음

```java
public class ExamConsole {
    Exam exam; // 상위 추상 클래스 타입으로 선언
    ExamConsole(Exam e) { this.exam = e; } // 업캐스팅 초기화
}
```

### 명확한 계층 구조 추상화

- 단순 중복 멤버 제거를 넘어 클래스끼리 **명확한 계층 구조**가 필요할 때 사용
- 추상클래스는 '클래스로서' **클래스와 의미 있는 연관 관계를 구축**할 때 사용
- 예: 삼각형·원·마름모 → 도형, 사자·호랑이·고양이 → 동물
- **SMS Sender 예시**: 통신사별 다른 커넥션 구현 + 공통 방해금지 모드 체크

```java
abstract class SMSSender {
    abstract public void establishConnectionWithYourTower();
    public void sendSMS() {
        establishConnectionWithYourTower();
        checkIfDoNotDisturbMode();
        destroyConnectionWithYourTower();
    }
    abstract public void destroyConnectionWithYourTower();
    public void checkIfDoNotDisturbMode() { /* 공통 구현 */ }
}
class SKT extends SMSSender { /* SKT 방식 구현 */ }
class LG extends SMSSender { /* LG 방식 구현 */ }
```

## 인터페이스를 사용하는 경우

- 어플리케이션의 기능을 정의해야 하지만 구현 방식이나 대상에 대해 추상화할 때
- **서로 관련성이 없는 클래스들을 묶어 주고 싶을 때** (형제 관계)
- **다중 상속(구현)**을 통한 추상화 설계가 필요할 때
- 특정 데이터 타입의 행동을 명시하고 싶은데, 어디서 그 행동이 구현되는지는 신경 쓰지 않는 경우
- **구현 객체가 같은 동작을 한다는 것을 보장**하기 위해 사용

### 자유로운 타입 묶음

- `extends`(상속)는 **논리적인 타입 묶음**의 의미
- `implements`(구현)는 **자유로운 타입 묶음**의 의미 → 논리적으로 관련 없는 클래스끼리 형제 타입처럼 묶음

**문제 상황**: Creature-Animal-Fish 상속 구조에서 수영(`swimming()`)을 People과 Whale에만 추가할 때, Creature에 추상 메소드를 추가하면 Tiger·Parrot에도 강제 구현이 필요해짐

**해결**: 인터페이스로 분리

```java
interface Swimmable { void swimming(); }
interface Flyable { void flying(); }
interface Talkable { void talking(); }

class Tiger extends Animal { } // Swimmable 구현 안 함
class Parrot extends Animal implements Talkable { ... }
class People extends Animal implements Talkable, Swimmable { ... } // 다중 구현
class Whale extends Fish implements Swimmable { ... }
```

### 인터페이스 다형성 이용 설계

- 인터페이스는 **그때그때 필요에 따라 구현해서 자유롭게 붙였다 떼었다** 하는 느낌
- 인터페이스 타입을 중개 타입으로 활용하여, 서로 전혀 연관 없는 클래스들을 **인터페이스로 타입 통합**

```java
interface Storable { int getData(); }
class FileSaver {
    Storable target; // 인터페이스 타입 필드
    int save() { int data = target.getData(); ... }
}
// 관련 없는 클래스들이 Storable을 implements하여 FileSaver에 전달 가능
class Exam implements Storable, Caculatable { ... }
class File implements Storable { ... }
```

## 마커 인터페이스

- **아무 메소드도 선언하지 않은 빈 껍데기 인터페이스**
- 역할: **객체의 타입과 관련된 정보만 제공** (단순 타입 체크용)
- `instanceof` 연산자로 일일이 클래스 타입을 구분하는 코드를 단순화

```java
interface Breedable {} // 마커 인터페이스

class Animal {
    public static void born(Animal a) {
        if(a instanceof Breedable) System.out.println("새끼를 낳았습니다.");
        else System.out.println("알을 낳았습니다.");
    }
}
class Lion extends Animal implements Breedable { }
class Chicken extends Animal { }
```

- 대표적인 자바 마커 인터페이스: **Serializable**, **Cloneable**

## 인터페이스 + 추상클래스 조합

- **추상클래스의 중복 멤버 통합** + **인터페이스의 다중 상속**을 동시에 활용하기 위한 조합
- 이 조합 패턴들이 **디자인 패턴**의 근간

### 추상클래스에 인터페이스 일부 구현

```java
interface Animal { void walk(); void run(); void breed(); }
abstract class Mammalia implements Animal {
    public void walk() { ... }
    public void run() { ... }
    // breed()는 구현하지 않아 자식 클래스에서 강제 구현
}
class Lion extends Mammalia {
    @Override public void breed() { ... }
}
```

### Interface - Abstract - Concrete Class 디자인 패턴

**문제**: 인터페이스는 중복 필드를 통합 못함 → 구현 클래스마다 중복 코드 발생

```java
// 중복 발생
class Rectangle implements IShape { double opacity; String color; ... }
class Square implements IShape { double opacity; String color; ... }
```

**해결**: 인터페이스와 구체 클래스 중간에 **추상클래스를 두어 공통 부분 통합**

```java
abstract class Shape implements IShape {
    protected double opacity;
    protected String color;
    public void setOpacity(double opacity) { this.opacity = opacity; }
    public void setColor(String color) { this.color = color; }
    // draw()는 구현 안 함
}
class Rectangle extends Shape {
    public void draw() { System.out.println(opacity + ", " + color); }
}
class Square extends Shape {
    public void draw() { System.out.println(opacity + ", " + color); }
}
```

- **단점**: 클래스 상속 기반이므로 다른 클래스를 상속 받아야 하는 경우 이 패턴 활용 불가
- 이 경우 **Adapter 패턴** 활용
