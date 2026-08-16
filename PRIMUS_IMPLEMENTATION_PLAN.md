# Primus 구현 계획서

상태: 설계 초안 1.0  
작성일: 2026-08-03  
목적: `loop-evolution`을 실행 가능한 진화 커널로 삼고 ECR, Frontier, Harness Relay의 엄격한 실험 원리를 흡수해, 공통 Core와 도메인별 Expert가 공존하는 MoE형 재귀적 에이전틱 개선 시스템을 구축한다.

## 1. 목표

Primus는 모델 가중치를 학습하는 시스템이 아니다. 고정된 모델과 평가 경계 안에서 다음 세 구성요소를 독립적으로 개선한다.

1. **Core Harness**: 모든 도메인에 적용되는 계약, 상태, 가설, 증거, Frontier, 복구 및 종료 규칙.
2. **Expert Harnesses**: Chess, Coding, Research, Math 등 특정 문제군에서 뾰족한 성능을 내는 실행 구조.
3. **Router Harness**: TaskProfile을 보고 사용할 Expert를 선택하는 에이전트와 검증·fallback 구조.

Primus의 최상위 목표는 다음과 같다.

```text
현재 Primus snapshot으로 실제 작업 수행
→ 실패와 성공 증거 축적
→ Core/Router/Expert 중 한 축에 대한 구조 가설 생성
→ incumbent와 challenger를 동일 조건에서 평가
→ 증거가 있는 구성요소만 승격
→ 통합 검증을 통과한 조합을 다음 Primus snapshot으로 활성화
```

## 2. 비목표와 불변 경계

다음 요소는 진화 대상이 아니다.

- 기반 모델 가중치
- hidden answer 및 비공개 evaluator
- 실행 도중의 승격 threshold
- 이미 완료된 라운드의 판정 규칙
- 인증·sandbox·권한 경계
- 부정행위 및 provenance 검사

후보가 모델, effort, benchmark, evaluator, 승격 규칙 또는 hidden truth 접근을 변경하면 즉시 무효다.

## 3. 전체 아키텍처

```text
Primus
├─ Runtime Plane
│  ├─ Task Ingestion
│  ├─ Shared Core Harness
│  ├─ Task Profiler
│  ├─ Router Harness
│  ├─ Expert Registry
│  ├─ ECR Transaction Runtime
│  ├─ Frontier Manager
│  └─ Verifier/Audit
├─ Evolution Lab
│  ├─ Architect
│  ├─ Candidate Factory
│  ├─ Constitutional Kernel
│  └─ Failure Clusterer
├─ Evaluation Relay
│  ├─ Static Gate
│  ├─ Cheap Probe
│  ├─ Development Pairs
│  ├─ Promotion Pairs
│  └─ Holdout/Recertification
├─ Control Plane
│  ├─ Champion Registry
│  ├─ Experiment Registry
│  ├─ Promotion Authority
│  ├─ Snapshot Manager
│  └─ Rollback
└─ Task Packages
   ├─ Chess
   ├─ Coding
   ├─ Research
   └─ future domains
```

## 4. 일반 작업 실행 파이프라인

```text
사용자 요청
→ Task Ingestion
→ Core가 실행 계약 생성
→ Task Profiler가 특징 추출
→ Router가 Expert 선택
→ Core + Expert가 ECR 규율 아래 문제 해결
→ Frontier가 실행 중 최고 유효 artifact 보존
→ 도메인 evaluator 실행
→ 공통 verifier/audit
→ 최종 artifact와 evidence receipt 반환
```

### 4.1 Task Contract

모든 작업은 최소한 다음 공통 계약으로 정규화한다.

```json
{
  "goal": "string",
  "artifact_type": "string",
  "acceptance": [],
  "rejection": [],
  "allowed_sources": [],
  "protected_behavior": [],
  "capabilities": [],
  "budget": {},
  "termination": {}
}
```

### 4.2 TaskProfile

Router 입력은 도메인 이름이 아니라 검증 가능한 문제 특성이다.

```text
artifact_type
repository_mutation_required
external_search_required
citation_required
formal_verifier_available
interactive_environment
state_horizon
risk_level
available_evaluator
required_capabilities
```

### 4.3 Router Decision

```json
{
  "selected_expert": "coding",
  "confidence": 0.91,
  "reason_codes": ["repository_mutation", "executable_tests"],
  "fallback": "general"
}
```

기본 실행은 `Core + Expert 1개`다. 낮은 confidence 또는 높은 위험도에서만 제한된 2-Expert 비교를 허용한다. 모든 Expert를 항상 실행하는 방식은 금지한다.

## 5. ECR 계약

모든 구조 변경과 중요한 artifact 변경은 수정 전에 다음을 등록한다.

```json
{
  "observed_bottleneck": "string",
  "hypothesis": "string",
  "proposed_change": "string",
  "predicted_observation": "string",
  "protected_behavior": [],
  "falsifier": "string",
  "stop_condition": "string"
}
```

실행 후 host가 결과를 다음 중 하나로 판정한다.

- `SUPPORTED`: 사전 예측과 관측이 일치한다.
- `FALSIFIED`: 관측이 가설과 모순된다.
- `UNRESOLVED`: 실행 실패나 부족한 증거 때문에 판단할 수 없다.

품질 승격과 인과 가설 판정은 분리한다. 성능이 좋아도 설명이 틀리면 후보 품질은 보존할 수 있지만 가설을 사실로 기록하지 않는다.

## 6. Frontier 계약

각 독립 실행은 여러 중간 artifact를 만들 수 있다. Host는 artifact bytes, SHA, validity, public score 및 failure class를 append-only journal에 보존한다.

```text
한 독립 실행 내부:
v1 → 70
v2 → 85  (frontier champion)
v3 → invalid
종료 → v2 복구
```

다음 두 선택을 엄격히 구분한다.

```text
독립 실행 내부: 최고 public-valid artifact 보존
여러 독립 실행 사이: 최고를 고르지 않고 사전 정의된 중앙값 대표 규칙 적용
```

이 구분으로 terminal regression은 방지하면서 best-of-N 선택 편향은 막는다.

## 7. Champion 계층

Primus는 하나의 champion이 아니라 독립 계보를 관리한다.

```text
Primus Release Snapshot
├─ Core Champion ID
├─ Router Champion ID
├─ General Expert Champion ID
├─ Chess Expert Champion ID
├─ Coding Expert Champion ID
├─ Research Expert Champion ID
├─ Task Adapter Versions
├─ Evaluator Versions
└─ Promotion Protocol ID
```

### 7.1 Core Champion

- 여러 도메인에서 검증된 공통 harness다.
- 특정 도메인 artifact와 공동 승격하지 않는다.
- 다중 도메인 evidence manifest를 승격 근거로 보존한다.

### 7.2 Expert Champion

- 특정 도메인의 LoopPlan이다.
- 해당 loop가 만든 중앙값 대표 artifact와 공동 승격할 수 있다.
- 승격은 niche claim이며 Core 개선으로 간주하지 않는다.

### 7.3 Router Champion

- TaskProfile에서 Expert를 선택하는 정책과 검증·fallback harness다.
- Core 및 Expert가 고정된 상태에서만 평가한다.

## 8. 독립 진화축

한 실험에서는 반드시 한 축만 변경한다.

### 8.1 Core Evolution

```text
Core incumbent
→ ECR 가설
→ Core challenger
→ Router와 모든 Expert 고정
→ 여러 개발 도메인 paired evaluation
→ holdout task/domain
→ Core Relay 승격
```

승격에는 macro improvement, worst-domain 보호, catastrophic regression 부재 및 예산 준수가 필요하다.

### 8.2 Expert Evolution

```text
Expert incumbent
→ 도메인 구조 가설
→ Expert challenger LoopPlan
→ Core와 Router 고정
→ 동일 anchor matched pairs
→ 도메인 holdout
→ Expert Relay 승격
```

기존 `loop-evolution`의 3-pair 및 중앙값 대표 artifact 규칙을 초기 계약으로 사용한다.

### 8.3 Router Evolution

```text
Router incumbent
→ routing policy challenger
→ Core와 모든 Expert 고정
→ 다중 도메인 route 실행
→ 고정 audit subset에서 counterfactual Expert 평가
→ quality/cost/regret 비교
→ Router Relay 승격
```

Router 평가는 최종 작업 품질, selection regret, invalid/crash, 비용, 지연시간 및 fallback 비율을 포함한다.

## 9. 단계형 Evaluation Relay

모든 후보를 처음부터 정식 다중 도메인 평가에 보내지 않는다.

```text
P0 Static Gate
→ P1 Cheap Probe
→ P2 Development
→ P3 Promotion
→ P4 Holdout
→ P5 Recertification
```

### P0: Static Gate

- schema/type 검사
- graph 연결 검사
- protected field 검사
- 중복 fingerprint 검사
- hidden/benchmark hardcode 검사
- 한 축만 변경했는지 검사

### P1: Cheap Probe

- 1개 도메인
- 1 pair
- 작은 공개 평가 세트
- 명백한 failure 및 invalid 조기 제거

### P2: Development

- Expert 후보: 해당 도메인의 개발 suite
- Router 후보: 여러 도메인의 routing suite
- Core 후보: 여러 개발 도메인

### P3: Promotion

초기 matched-pair 계약:

```text
3 pairs completed
candidate wins > losses
candidate median > incumbent median
candidate invalid count = 0
```

Core는 여기에 다중 도메인 비회귀 조건을 추가한다.

### P4: Holdout

- 개발 중 사용하지 않은 task, seed, case payload 사용
- Core에는 가능하면 holdout domain 포함
- 개발과 holdout의 ID 및 payload 중복 금지

### P5: Recertification

구조 단순화나 ablation을 수행했다면 최종 bytes를 새 holdout에서 다시 인증한다.

## 10. Expert 생명주기

### 생성

다음 조건을 만족할 때만 shadow Expert를 만든다.

- 독립 작업에서 유사 failure가 반복된다.
- Core와 기존 Expert가 해결하지 못한다.
- 실패 cluster가 task 이름이 아니라 mechanism으로 정의된다.
- 추가 비용을 상쇄하는 전문 lift 가설이 있다.

### 승격

General Expert 및 해당 niche incumbent와 비교해 유효한 holdout lift가 있을 때 registry에 등록한다.

### 증류

여러 Expert에서 공통으로 성공한 원리는 도메인 표현을 제거한 Core 후보로 다시 제안한다. Expert 성공을 Core에 직접 복사하지 않는다.

### 정리

다음 조건에서 prune 또는 merge를 검토한다.

- 장기간 선택되지 않는다.
- General Expert 대비 lift가 없다.
- 다른 Expert와 행동·성능이 중복된다.
- 비용 대비 효용이 낮다.
- holdout에서 전문성이 재현되지 않는다.

## 11. 상태와 증거

모든 계보는 다음 정보를 append-only로 보존한다.

- parent/candidate ID 및 content hash
- ECR 가설과 사전 예측
- 실행 manifest와 모델/effort/tool/budget
- raw prompts, responses, stderr 및 parsed outputs
- artifact bytes와 SHA
- public/holdout evaluation receipts
- 승격·거절·중단 이유
- 인과 판정
- rollback 및 supersession 기록

동일 fingerprint의 완료·실패·중단 후보를 조용히 재실행하지 않는다.

## 12. 제안 디렉터리 구조

```text
primus/
├─ src/primus/
│  ├─ runtime/
│  │  ├─ task_contract.py
│  │  ├─ profiler.py
│  │  ├─ router.py
│  │  └─ executor.py
│  ├─ evolution/
│  │  ├─ architect.py
│  │  ├─ ecr.py
│  │  ├─ frontier.py
│  │  ├─ relay.py
│  │  └─ candidate.py
│  ├─ control/
│  │  ├─ kernel.py
│  │  ├─ registry.py
│  │  ├─ promotion.py
│  │  └─ snapshot.py
│  ├─ experts/
│  │  ├─ registry.py
│  │  └─ interfaces.py
│  └─ tasks/
│     ├─ interfaces.py
│     └─ repository.py
├─ experiments/
│  ├─ core/
│  ├─ router/
│  └─ experts/
├─ resources/
│  ├─ models/
│  ├─ benchmarks/
│  └─ policies/
├─ imports/
│  └─ loop-evolution-chess/
├─ tests/
└─ docs/
```

## 13. 기존 loop-evolution 이관 원칙

`loop-evolution`은 삭제하거나 직접 재작성하지 않는다. 해시가 있는 읽기 전용 source import로 보존한 뒤 필요한 코드를 Primus 경계에 맞게 단계적으로 가져온다.

초기 대응:

```text
EvolutionPipeline → Primus Evolution Kernel
Architect         → Component Architect
LoopExecutor      → Expert Executor
LoopPlan          → Expert Harness Plan
StateStore        → Champion/Experiment Registry
batch judge       → Expert Relay 초기 승격 규칙
ChessBench        → Chess Task Package/Evaluator
현재 chess 계보   → 최초 Chess Expert lineage
```

이관 전후 파일 hash와 변환 규칙을 manifest로 남긴다. 기존 라운드 결과를 새 승격 규칙으로 소급 재해석하지 않는다.

## 14. 구현 단계

### Phase 0: 동결과 부트스트랩

- 현재 `loop-evolution` 코드, 정책, 체스 benchmark, champion package hash 기록
- Primus 저장소와 기본 테스트 환경 생성
- 기존 결과를 읽기 전용 import로 보존

완료 조건: 동일한 champion 구조와 대표 engine provenance를 Primus에서 읽고 검증할 수 있다.

### Phase 1: Expert Evolution Kernel

- 범용 이름으로 계약 정리
- Chess Task Package adapter 구현
- 기존 3-pair Expert 승격 결과 재현
- append-only experiment registry 구축

완료 조건: Primus가 기존 체스 Expert 라운드를 동등한 계약으로 실행할 수 있다.

### Phase 2: ECR Gate

- 사전 가설 schema 및 host receipt 구현
- prediction/observation 판정 구현
- unbound mutation 평가 제외
- falsified hypothesis ledger 구현

완료 조건: ECR receipt 없는 변경은 승격 증거가 될 수 없다.

### Phase 3: Frontier

- 실행 내부 artifact snapshot journal
- public-valid incumbent 선택
- invalid terminal artifact 자동 복구
- 독립 실행 간 best-of-N 금지 검사

완료 조건: terminal regression이 발생해도 해당 실행의 최고 유효 artifact가 보존된다.

### Phase 4: 두 번째 Expert

- Coding Task Package와 deterministic evaluator 추가
- General Expert 초기 구조 정의
- Chess/Core 용어가 공통 계약에 누출되지 않는지 감사

완료 조건: 동일 Core 인터페이스로 Chess와 Coding을 모두 실행할 수 있다.

### Phase 5: Core Relay

- Core와 Expert champion 분리
- 다중 도메인 Core paired evaluation
- macro/worst-domain/non-regression 판정
- holdout task 및 domain 경계 구현

완료 조건: 특정 도메인 lift만으로 Core가 승격되지 않는다.

### Phase 6: Router Harness

- 결정론적 Task Profiler
- 구조화된 Router Agent 출력
- capability validator와 fallback
- 초기 고정 Router 구축

완료 조건: Router 결과가 재현 가능한 manifest와 함께 기록되고 잘못된 선택이 fail-closed 처리된다.

### Phase 7: Router Evolution

- route candidate 계보
- counterfactual audit subset
- selection regret와 비용 평가
- Router 전용 Relay

완료 조건: Core와 Expert를 변경하지 않고 Router만 독립 승격할 수 있다.

### Phase 8: Expert 생명주기와 Primus Release

- failure clustering 기반 Expert 생성
- prune/merge/distill 제안
- 전체 integration suite
- 서명된 release snapshot과 component rollback

완료 조건: 구성요소 승격과 serving snapshot 활성화가 분리되고 원자적으로 검증된다.

## 15. 핵심 테스트

### 불변성

- 후보가 모델·benchmark·evaluator·승격 규칙을 바꾸면 거절된다.
- 후보 생성기는 active champion pointer를 수정할 수 없다.
- evaluator는 promotion을 수행할 수 없다.
- Task Package가 Core 내부에 도메인 분기를 주입할 수 없다.

### ECR

- 사전 receipt 없는 mutation은 evidence-ineligible다.
- 예측 불일치가 `FALSIFIED`로 기록된다.
- 품질 승격과 인과 판정이 독립적이다.

### Frontier

- 마지막 artifact가 invalid여도 최고 유효 snapshot이 복구된다.
- 다른 독립 실행의 최고 artifact를 골라 대표로 만들 수 없다.
- artifact SHA와 evaluation receipt가 일치해야 한다.

### Relay

- 동일 anchor/model/effort/budget이 아니면 pair가 무효다.
- development와 holdout payload가 겹치면 승격할 수 없다.
- invalid candidate가 하나라도 있으면 초기 Expert promotion은 실패한다.
- 기존 완료 fingerprint를 조용히 재실행하지 않는다.

### Router

- 허용되지 않은 Expert ID는 fallback 또는 실패 처리한다.
- 선택 Expert의 capability가 TaskProfile 요구를 만족해야 한다.
- Router 평가 중 Core와 Expert hash가 고정된다.

### Snapshot

- 구성요소 certificate 없이 serving snapshot을 바꿀 수 없다.
- integration 실패 시 이전 snapshot으로 rollback한다.
- 모든 component lineage와 evaluator version을 재현할 수 있다.

## 16. 초기 운영 원칙

1. 사용자 작업 실행과 진화 실행을 분리한다.
2. 실패 한 건으로 진화를 시작하지 않고 반복 가능한 failure cluster를 요구한다.
3. Expert 진화는 자주, Router 진화는 충분한 route evidence가 쌓였을 때, Core 진화는 공통 실패가 확인됐을 때 수행한다.
4. 비싼 다중 도메인 검증은 Cheap Probe와 Development를 통과한 소수 후보에게만 수행한다.
5. 최초에는 Chess와 Coding 두 Expert만 두고 Router는 고정 규칙으로 시작한다.
6. Expert가 충분히 검증되기 전에는 Router Evolution을 활성화하지 않는다.
7. `general`, `universal`, `self-improving` 주장은 holdout 및 동일 조건 비교 범위 안에서만 사용한다.

## 17. 최종 설계 원칙

```text
범용성은 Core가 담당한다.
뾰족한 성능은 Expert가 담당한다.
선택 능력은 Router가 담당한다.
변경 규율은 ECR이 담당한다.
실행 중 최고 산출물 보존은 Frontier가 담당한다.
공정한 비교와 승격은 Relay가 담당한다.
최종 활성화와 rollback은 Control Plane이 담당한다.
```

Primus는 이 책임들을 섞지 않고 각각 독립적인 champion 계보와 증거 경계를 유지해야 한다.
