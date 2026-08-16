# Search cycle contract

탐색은 정식 챔피언과 육성 후보를 분리한다. 정식 챔피언은 3-pair 승격 계약을 이긴 패키지만 바뀐다.
반대가설 후보가 승격하지 못했더라도 챔피언 harness 중앙값 `score_rate`의 90% 이상을 유지하면 별도의
육성 후보가 된다. 음수 Elo에는 백분율을 적용하지 않는다. 두 pair 뒤 정식 승격이 이미 불가능하면
남은 pair의 `score_rate`를 0~1로 두고 최악·최선 중앙값 비율을 계산한다. 최선도 90% 미만이면 즉시
실패하고, 최악도 90% 이상이면 즉시 육성 등록하며, 경계가 90%를 걸치면 세 번째 pair를 실행한다.

```text
정식 챔피언의 general 2회 -> emergent 2회 -> counter_hypothesis

counter_hypothesis
  |-- 정식 승격 --------------------------> 새 챔피언, general
  |-- 유효 3-pair + 상대 성능 90% 이상 ---> 육성 후보, general 0/2
  `-- 미달 또는 무효 ----------------------> counter_hypothesis 반복

육성 후보
  general 유효 2회 -> emergent 유효 2회
  |-- 어느 라운드에서든 정식 승격 --------> 새 챔피언
  `-- 네 번 동안 미승격 ------------------> 육성 계열 폐기, counter_hypothesis
```

무효 batch는 general·emergent 횟수를 소비하지 않는다. 반대가설과 육성 라운드는 정식 승격 불가능이
확정된 뒤 90% 자격 또는 계열 내 개선 여부까지 수학적으로 결정되면 두 valid pair에서 끝낼 수 있다.
경계가 겹치면 세 번째 pair를 실행한다. pair가 재시도 후에도 무효이면 batch는 inconclusive이며 육성
자격을 얻지 못한다.

## General refinement

활성 육성 후보가 없으면 `general`은 정식 챔피언 계열을, 있으면 육성 후보 계열의 현재 최고 구조를
설계 부모로 사용한다. 거시적 계열은 유지하면서 증거에 근거한 인과 요소 하나만 개선한다. 유효
라운드는 승격 여부와 무관하게 두 번의 예산 중 하나를 소비한다. 육성 중 후보가 정식 챔피언을
이기지는 못했지만 육성 incumbent보다 상대 `score_rate` 비율이 높으면 다음 라운드의 설계 부모가 된다.

## Emergent exploration

창발 후보는 설계 부모의 계열을 유지하면서 기존 제어 흐름에 없던 관찰 가능한 행동 경로 하나를
만든다. 패킷 필드 추가, 인증서 확장, 감사 위치 이동, reviewer/gate 추가는 그 자체로 창발성이 아니다.
새로운 trigger 기반 상태전이와 결정 경로가 있어야 한다. 두 번의 유효 창발 라운드는 서로 다른
`capability_family`를 사용한다.

육성 계열이 general 두 번과 emergent 두 번 안에 정식 승격하지 못하면 활성 상태에서 제거한다. 원본
라운드와 감사 기록은 보존하지만 다음 후보의 부모로 사용하지 않는다.

## Strengthened counter hypothesis

반대가설은 챔피언을 조금 뒤집거나 단계 순서만 바꾸는 모드가 아니다. 기존 계열을 부모로 사용하지
않고 다음 항목을 구조화해 제출한다.

- 챔피언 계열의 핵심 인과 원리
- 부정할 핵심 가정 1~2개
- 이름을 바꿔서도 재사용할 수 없는 챔피언 메커니즘
- 독립적인 대체 인과 원리와 안정된 `alternative_family`
- 정보 흐름·오류 발견·후보 선택·최종 결정·실패 복구 중 최소 두 차원의 행동 차이
- 같은 증거에서 기존 계열과 구분되는 `non_derivative_probe`

최근 반대가설에서 시험한 `alternative_family`는 bounded history 안에서 다시 제안할 수 없다. 새 계열
후보가 바로 정식 승격하면 육성 없이 챔피언이 된다. 미승격이면서 정확한 3-pair 비율 또는 보수적인
2-pair 하한이 90% 이상이면 육성 후보가 되고, 상한도 90% 미만이면 반대가설 탐색을 계속한다.

## Proposal validation and accounting

독립 Sol max 구조 설계자 제안이 스키마나 현재 탐색 단계 계약을 위반하면 Luna high 내부 루프를 실행하지 않는다. 원본
prompt, response, token receipt, validation error를 `generation/attempts`에 보존하고 설정된 한도 안에서
검증 피드백을 포함해 재제안한다. 실패 제안 토큰도 라운드의 Sol 비용과
`proposal_invalid_spend`에 포함한다.

설계 시작 전에 모델·reasoning effort·독립 서브에이전트 모드를 해시한
`generation/architect-session.json`을 기록한다. 재개 시 session/receipt 출처가 현재 정책과 다르거나
없는 partial plan은 재사용하지 않고 명시적으로 중단·보존한 뒤 새 정책으로 다시 설계한다.
