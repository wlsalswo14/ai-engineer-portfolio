# Architecture

## 경계

`loop_evolution`의 핵심 책임은 후보 루프 제안, 구조 검증, matched-pair 실행, 평가 판정, 구조와
대표 산출물의 공동 승격, 정체 상태 관리다. 체스 문제 자체와 모델 호출 방식은 핵심 로직 밖의
어댑터로 취급한다.

```text
experiment config
       |
       v
EvolutionPipeline
  |-- Architect ---------- model backend adapter
  |-- LoopExecutor ------- model backend adapter
  |-- ExistingChessBench - benchmark adapter
  |-- StateStore --------- experiment workspace
  `-- batch judge -------- pure promotion rules
```

## 모듈 책임

- `pipeline.py`: 한 라운드의 오케스트레이션만 담당한다.
- `plan.py`: 루프 구조 스키마와 금지 구조를 검증한다.
- `batch.py`: 3-pair 승격 규칙을 순수 함수로 계산한다.
- `state.py`: 챔피언, local→emergent→counter 탐색 상태, bounded capsule, append-only archive를 관리한다.
- `agents.py`: 구조 제안과 구조 실행을 모델 백엔드에 연결한다.
- `evaluator.py`: 산출물을 동결된 평가 계약에 연결한다.
- `platform/`: Codex 실행과 ChessBench 계약의 로컬 어댑터다. 핵심 진화 정책을 넣지 않는다.

## 의존 방향

핵심 모듈은 `V3 lite`를 import하지 않는다. 외부 구현에서 가져와야 할 기능은 `platform` 안에서
끝나야 한다. 새로운 벤치마크를 추가할 때는 기존 체스 평가기를 수정하지 않고 새 어댑터와 새
실험 설정을 추가한다.

## 상태와 이력

`experiments/<id>/workspace` 하나가 한 계보의 권위 있는 상태다. `state.json`은 현재 상태,
`state-capsule.json`은 xhigh에 전달할 제한된 입력, `archive/rounds.jsonl`은 전체 라운드 색인이다.
라운드 원본은 수정하지 않는 것이 원칙이다. 위치 이관처럼 경로 문자열을 기계적으로 바꾸는 경우에는
반드시 `migration`에 변경 전후 해시를 남긴다.

ChessBench 케이스의 `metadata.result_dir`은 기존 contract hash를 유지하기 위한 동결 필드다. 실제 결과
읽기·쓰기는 실험 설정의 `benchmark_result_dir`로 재지정한다. 따라서 과거 캐시는 그대로 재사용하지만
새 평가는 V3 lite가 아니라 현재 실험의 `workspace/benchmark-results`에 저장된다.

## 변경 원칙

1. 진화 정책 변경과 체스 실험 계약 변경을 한 커밋에서 섞지 않는다.
2. 승격 규칙을 변경할 때는 기존 라운드를 재해석하지 말고 새 protocol id를 사용한다.
3. 후보 생성 프롬프트가 커질 때는 전체 이력을 넣지 않고 bounded capsule 한도를 조정한다.
4. 벤치마크·정책·최초 챔피언 자료는 해시가 바뀌지 않게 동결한다.
5. `workspace`를 삭제하거나 초기화하기 전에 별도 체크포인트를 검증한다.
6. 창발성은 호출 수나 토폴로지가 아니라 새 trigger 기반 상태전이와 관찰 가능한 행동으로 검증한다.
