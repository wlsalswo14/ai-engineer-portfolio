# Evaluation Protocol v2

## 1. 공개 포트폴리오 예선

설정의 `portfolio_size`가 2 이상이면 서로 다른 탐색 방식으로 후보 Harness를 만듭니다. 모든 후보는 같은 공개 소형 과제를 풀고 다음 순서로 정렬됩니다.

1. 유효한 결과 비율
2. 공개 품질
3. 더 낮은 생성 비용

선택된 한 후보만 정식 공개 비교와 비공개 인증으로 갑니다. 포트폴리오 결과에는 hidden 정보가 없습니다.

## 2. 공개 matched screening

현 챔피언과 후보는 같은 공개 과제, 같은 복제 번호로 비교됩니다. 모든 arm을 생성하고 봉인한 뒤 평가합니다.

후보가 품질 기준을 통과하거나, 허용 범위 안에서 품질을 유지하면서 설정된 비율 이상 비용을 줄여야 다음 단계로 갑니다. 품질 점수에서 토큰 벌점을 빼 하나의 불투명한 숫자로 만들지 않습니다.

공개 결과만 다음 두 기억으로 바뀔 수 있습니다.

- 행동 피드백: 무엇이 잘못됐고 무엇을 지켜야 하는가
- 실험 lesson: 무엇을 바꿨고 비교 결과의 방향이 어땠는가

## 3. 부분 품질과 무효 제출

`valid`는 “정답인가”가 아니라 “평가 가능한 계약을 지켰는가”입니다.

- Coding 테스트 일부 실패: valid, 통과율 0~1
- Reasoning 오답: valid, 점수 0
- 보호 파일 변경: invalid
- 금지 도구 사용: invalid
- 평가기 바이너리/fixture/worker 장애: infrastructure error

이 구분 덕분에 7/10짜리 개선 신호를 잃지 않으면서, 규칙을 어긴 제출은 계속 차단합니다. 기존 챔피언이 특정 과제에서 무효이고 후보가 유효하면 후보의 복구 승리로 셉니다.

## 4. 의미 기반 hidden 1회 사용

Hidden 선택의 ID가 아니라 평가에 영향을 주는 내용을 해시합니다.

- 실제 request와 fixture 파일 해시
- seed와 실행 조건
- evaluator/runner/opening/Stockfish 고정 해시
- 채점 방식과 허용 도구
- `selection_unit`: 개별 case 또는 전체 suite

ID 변경과 순서 변경은 새 증거가 아닙니다. 동일한 의미 지문은 다른 run에서 다시 소비할 수 없습니다.

라운드 시작 전에 다음 hidden 선택의 의미 지문을 계산해 이미 사용됐는지 확인합니다. 소진됐다면 후보 생성 전에 멈춥니다. `primus doctor`는 `semantic_cases`와 예상 `hidden_selection_capacity`를 표시합니다.

ChessBench100은 50개 opening 전체와 100게임 일정이 한 평가 suite이므로 `selection_unit=suite`입니다. 현재 taskset의 ID 40개는 새 hidden 증거 40개가 아니라 의미상 suite 1개입니다.

## 5. 독립 hidden 인증

Hidden 단계에는 incumbent와 공개 단계에서 선택된 후보 하나만 들어갑니다. 공개 probe에서 탈락한 후보는 hidden을 보지 않습니다.

인증은 다음을 요구합니다.

- 후보 arm 계약 유효
- matched pair 다수 승리
- 최소 효과
- 양수인 bootstrap 하한, 또는 설정된 품질 비퇴보 + 비용 절감 경로
- 허용 invalid rate

상세 hidden 결과는 immutable receipt에는 남지만 설계자 기억으로 역류하지 않습니다.

## 6. 승격

Hidden은 승격 여부만 결정합니다.

- `domain_lineage`: 공개 screening에서 봉인한 Artifact와 후보 Harness를 승격
- `task_local`: 후보 Harness만 승격하고 특정 과제 답은 승격하지 않음

SQLite 한 트랜잭션 안에서 기존 active 챔피언을 superseded로 바꾸고 새 챔피언을 active로 만듭니다.
