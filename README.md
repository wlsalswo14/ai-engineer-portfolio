# Ouroboros Loop Evolution

문제를 푸는 코드 하나가 아니라, 그 코드를 만들어 내는 **에이전트 루프 구조**를 챔피언으로 두고
재귀적으로 개선하는 독립 시스템이다. 현재 공식 `chess-tier5-clean` 실험에서는 루프 구조와 그 구조가 만든
대표 체스 엔진을 하나의 승격 패키지로 관리한다.

이 프로젝트는 `V3 lite`의 후속 실행 폴더가 아니다. V3 lite에서 필요한 모델 실행기와 ChessBench
계약은 `src/loop_evolution/platform`이라는 안정된 어댑터 경계 안으로 가져왔고, 최초 R20 자료는
`imports/v3-lite-r20`에 동결했다. 이후 라운드는 V3 lite에 기록하지 않는다.

## 디렉터리

```text
loop-evolution/
├─ src/loop_evolution/                 # 범용 루프 진화 엔진
│  └─ platform/                        # 모델·벤치마크 로컬 어댑터
├─ experiments/chess-tier5-clean/
│  ├─ config.json                      # 체스 실험 계약
│  └─ workspace/                       # 깨끗한 공식 계보와 로컬 결과 캐시
├─ experiments/chess-tier5/            # 이전 R0~R21 및 중단된 R22 연구 이력(비공식 보존본)
├─ resources/
│  ├─ policies/                        # Sol xhigh / Luna high 정책
│  └─ benchmarks/chessbench100-tier5/  # 동결 ChessBench100 입력
├─ imports/v3-lite-r20/                # 최초 챔피언 자료
├─ migration/                          # 이관 감사 기록
├─ tools/                              # 유지보수 도구
└─ tests/
```

구조 원칙과 모듈 책임은 [ARCHITECTURE.md](ARCHITECTURE.md), 이관 기록은
[MIGRATION.md](MIGRATION.md), 탐색 단계 계약은 [SEARCH-CYCLE.md](SEARCH-CYCLE.md)에 정리되어 있다.

## 현재 상태

- 완료 라운드: R28 (내부 clean 인덱스 R9)
- 현 챔피언: R26에서 승격된 `package_164862893ef916a4`
- 루프 구조: `loop_2c6ee2e0a1ec021b`
- 구조 형태: collaboration, 3-call provisional builder → causal attributor → certified rollback integrator
- 대표 엔진 Elo: `-105.297`
- R26 승격 근거: 유효 pair `1승 0패 2무`, 후보 중앙값 `-105.297` 대 incumbent `-120.412`
- R27: 창발 1회차 미승격·inconclusive, 유효 pair `1승`, 다음 pair 재시도 소진
- R28: 창발 2회차 미승격 `0승 2패`, 승격 불가능으로 조기 종료
- 탐색 상태: 국소개선 `2/2`, 창발 실패 `2/2`, 반대가설 모드
- 다음 라운드: R29 (내부 clean 인덱스 R10), 승격까지 반대가설 유지

공식 표시 번호는 내부 clean 인덱스에 19를 더한다. 이는 이름만 바꾸는 규칙이며 디렉터리,
구조 ID, 패키지 ID, 엔진, Elo, 감사 기록은 변경하지 않는다.

R21~R25의 anchor별 결과와 토큰 집계는
[experiments/chess-tier5-clean/R21-R25-REPORT.md](experiments/chess-tier5-clean/R21-R25-REPORT.md),
R26~R28 결과는
[experiments/chess-tier5-clean/R26-R28-REPORT.md](experiments/chess-tier5-clean/R26-R28-REPORT.md)에 있다.

이전 `chess-tier5` 계보는 무효 arm이 상대의 승리로 계산될 수 있었던 과거 판정의 영향을 받아
공식 상태에서 제외했다. 삭제하지 않고 감사·연구용으로 보존한다.

## 실행

프로젝트 루트에서 실행한다. 기본 설정은 자동으로
`experiments/chess-tier5-clean/config.json`을 사용한다.

```powershell
python run.py status
python run.py propose
python run.py run-round
python run.py calibrate-direct
```

다른 실험은 설정 파일을 명시한다.

```powershell
python run.py status --config experiments\another-experiment\config.json
```

`init`은 비어 있는 새 작업공간에만 사용한다. 현재 공식 작업공간에는 다시 실행하지 않는다.

## 승격 계약

각 라운드는 시작 전에 현재 챔피언, 동결 계보 baseline, 최근 승격의 비대표 유효 산출물로 구성된
anchor 3개를 확정한다. 각 pair에서는 챔피언 루프와 후보 루프가 같은 anchor를 받지만, 세 pair의
anchor는 서로 다르다. 패널은 라운드 도중 바뀌지 않고 승격 뒤에만 승격 유래 슬롯이 갱신된다.

```text
pair win: candidate Elo > incumbent Elo

batch promotion:
  exactly 3 fully valid pairs completed
  candidate wins > candidate losses
  candidate median Elo > incumbent median Elo
  candidate invalid count = 0
  incumbent invalid count = 0
```

어느 한쪽이라도 무효이면 그 시도의 양쪽 결과를 모두 버리고 pair 전체를 다시 실행한다. 최대 3회
시도해도 유효 pair를 만들지 못하면 승패가 아니라 inconclusive로 끝낸다.

각 라운드는 Sol xhigh 구조 제안 비용과 Luna high 내부 루프 비용을 분리해
`evaluation/token-accounting.json`에 기록한다. 입력·캐시 입력·출력·reasoning 출력·호출 수와 무효
재시도 비용을 arm/pair/round 단위로 집계한다. reasoning 출력은 출력 토큰의 부분집합이므로 총합에
다시 더하지 않으며, 현재 토큰 비용은 관측 지표일 뿐 승격 조건에는 영향을 주지 않는다.

후보의 최고 엔진을 골라내지 않는다. 중앙값 순위의 후보 엔진과 그 후보 루프 구조가 함께 승격한다.
국소개선은 승격 여부와 무관하게 두 번만 시험한 뒤 창발 탐색으로 넘어간다. 서로 다른 창발 능력
후보가 두 번 연속 미승격하면 반대가설 모드가 시작되고, 다음 승격까지 유지된다. 복제 후보·best-of-N·
단순 다량 생성은 구조 가설로 금지되어 있다.

## 검증

```powershell
python -m pytest -q
python -m compileall -q src run.py tools
python run.py status
```

프로젝트를 다시 옮길 때는 탐색 후 적용하는 두 단계로 경로를 변환한다.

```powershell
python tools\relocate_workspace.py --from-project OLD_ROOT --to-project NEW_ROOT
python tools\relocate_workspace.py --from-project OLD_ROOT --to-project NEW_ROOT --apply
```

원본 이력은 삭제하지 않는다. 새 위치가 충분히 검증된 뒤에도 이전 폴더는 읽기 전용 백업으로
보존하거나 별도 아카이브 정책에 따라 처리한다.
