# Architecture v2

## 한눈에 보는 구조

```text
                         Primus Core
  +----------------------------------------------------------+
  | 상태 머신 | 예산 | 공개 기억 | 적응 탐색 | 영수증 | 승격 |
  +--------------------------+-------------------------------+
                             |
             공통 DomainAdapter 계약(module:Class)
                             |
       +---------------------+-----------------------+
       |                     |                       |
    Chess                 Coding               새 도메인
  task/evaluator        task/evaluator        task/evaluator
```

본체는 특정 문제를 푸는 법을 모릅니다. 각 어댑터가 다음을 담당합니다.

- 공개/비공개 과제를 모델에게 보여줄 문자열로 변환
- 결과물 형식 확인
- 실제 평가 실행
- 점수, 부분 지표, 실패 종류 반환
- 문제의 의미상 지문 계산
- 기준 결과물의 저장 형식 해석

따라서 새 도메인을 추가할 때 본체의 분기문을 늘릴 필요가 없습니다.

## 라운드 흐름

```text
CREATED
  |
  +-- 공개 실험 기억으로 탐색 연산 선택
  +-- 후보 포트폴리오 생성 및 공개 probe
  v
PLANNED
  v
SCREEN_GENERATED -> SCREEN_EVALUATED
                           |
                    실패 -> FALSIFIED
                           |
                           v
                    SCREEN_PASSED
                           |
            domain_lineage 결과물은 여기서 봉인
                           v
                     PROVISIONAL
                           v
                     CERT_GENERATED
                           |
                 의미 기반 hidden 1회 소비
                           v
                    HIDDEN_EVALUATED
                      |             |
                   실패          CERTIFIED
                      |             |
                 FALSIFIED          v
                                 PROMOTED
```

`REJECTED`, `FALSIFIED`, `UNRESOLVED`, `PROMOTED`는 종료 상태입니다. 인프라 장애는 후보의 품질 실패로 바꾸지 않고, 증거를 남긴 채 같은 라운드를 재개할 수 있게 합니다.

## Harness와 Artifact

```text
Harness = 누가, 어떤 순서로, 무슨 정보를 넘기며 일하는가
Artifact = 그 작업법으로 이번 과제에서 만든 실제 결과물
```

두 승격 방식이 있습니다.

| 범위 | 예 | 승격되는 것 |
|---|---|---|
| `domain_lineage` | Chess 엔진, Cache 정책 | Harness + 공개 시험에서 미리 고른 Artifact |
| `task_local` | Coding 패치, Reasoning 답 | Harness만 승격; 이전 Artifact는 기준 기록으로만 보존 |

비공개 결과를 보고 “가장 잘 나온 결과물”을 고르지 않습니다. `domain_lineage` 배포 결과물은 공개 screening에서 미리 봉인됩니다. 비공개 시험은 이미 정해진 후보 작업법의 일반화 여부만 판단합니다.

## 공개 기억과 적응 탐색

`resources/public_lessons`에는 절대 점수 대신 비교 방향과 실험 맥락을 저장합니다. 설계자는 이 기억과 공개 행동 피드백만 볼 수 있습니다. Hidden receipt, 점수, 문제 내용은 입력 경로가 없습니다.

탐색 정책은 최근 실패 유형과 비용 방향에 따라 `add`, `delete`, `replace`, `recombine`, `de_novo`, `research_transfer` 중 다음 연산을 고릅니다. 다만 일정 주기마다 먼 탐색을 강제로 넣어 한 지역에 갇히는 것을 막습니다.

## 격리와 재개

각 모델 호출은 `calls/<call>/workspace`라는 빈 실행 폴더에서 수행됩니다. 모델에게 필요한 정보는 봉인된 프롬프트로만 전달됩니다. 호출 응답, 사용량, 프롬프트 해시는 workspace 바깥 영수증 폴더에 기록됩니다.

한 단계의 모든 결과물을 먼저 생성하고 `pre-evaluation-seal.json`을 만든 뒤 평가기를 엽니다. 중단 후 재개할 때 기존 프롬프트·응답·해시가 다르면 실패하고, 같으면 모델을 다시 호출하지 않습니다.

## 저장 무결성

- 챔피언 구조와 결과물: SHA-256 content-addressed object
- 전역 receipt: 이전 receipt 해시를 포함하는 체인
- 상태 변경: SQLite WAL + `BEGIN IMMEDIATE`
- 활성 포인터: 도메인당 정확히 하나
- 결과물 계보: `artifact_versions`
- 의미 기반 비공개 소비: `hidden_consumption`
- 공개 실험 기억: `experiment_lessons`
