# Search cycle contract

후보 탐색은 승격 여부와 별개인 세 단계 상태기로 제어한다.

```text
general (local refinement) -- two tested rounds --> emergent_exploration
emergent_exploration -- promotion -------------> general, counters reset
emergent_exploration -- two non-promotions ----> counter_hypothesis
counter_hypothesis -- non-promotion -----------> counter_hypothesis
counter_hypothesis -- promotion ---------------> general, counters reset
```

## Local refinement

`general` 라운드는 챔피언의 거시적 행동 능력을 유지하면서 인과 구조 요소 하나를 개선한다. 승격한
라운드도 `local_refinement_count`를 하나 소비한다. 두 라운드를 시험하면 성적과 무관하게 다음 후보는
`emergent_exploration`이어야 한다.

## Emergent exploration

창발 후보는 역할 수나 화살표 모양이 아니라 챔피언에게 없던 실행 경로 하나를 만들어야 한다. 제안은
다음 계약을 구조화해 제출한다.

- `capability_family`: 새 행동 계열의 안정된 이름
- `champion_limitation`: 챔피언이 구조상 할 수 없는 행동
- `emergent_capability`: 후보가 새로 수행하는 관찰 가능한 행동
- `trigger`: 새 행동을 발동하는 실행 중 증거
- `state_transition`: 발동 전후 작업 상태
- `observable_effect`: 같은 증거에서 챔피언과 달라지는 실행 궤적
- `novelty_probe`: 새 경로의 발생을 확인하는 probe
- `not_local_refinement`: 기존 인증·감사·롤백 세부화가 아닌 이유

패킷 필드 추가, 인증서 확장, 감사 위치 이동, reviewer/gate 추가는 그 자체로 창발성이 아니다. 새로운
trigger 기반 상태전이와 결정 경로가 있어야 한다. 첫 창발 후보가 미승격이면 두 번째 후보는 다른
`capability_family`를 사용해야 한다. 두 창발 후보가 모두 미승격이면 반대가설 모드로 전환한다.

## Counter hypothesis

반대가설 모드는 최근 탐색 방향의 지배 가정을 명시하고 뒤집는다. 한 번 시작되면 후보가 정식 승격할
때까지 유지된다. 승격하면 국소개선 횟수와 창발 실패 횟수를 모두 0으로 초기화한다.

## Proposal validation and accounting

Sol xhigh 제안이 스키마나 현재 탐색 단계 계약을 위반하면 Luna high 내부루프를 실행하지 않는다. 원본
prompt, response, token receipt, validation error를 `generation/attempts`에 보존하고 설정된 한도 안에서
검증 피드백을 포함해 재제안한다. 실패 제안 토큰도 라운드의 Sol 비용과
`proposal_invalid_spend`에 포함한다.
