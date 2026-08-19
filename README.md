# chess_bench — LLM 코드 생성 능력 평가 하네스

LLM에게 **파이썬 UCI 체스 엔진을 처음부터 작성**시키고, 생성된 `engine.py`를
실제로 구동해 Stockfish와 대국시켜 승패로 채점하는 벤치마크입니다.
"코드가 그럴듯한가"가 아니라 **"돌려봤을 때 이기는가"** 로 평가합니다.

1인 개발 · 2026.05 - 2026.06

## 구성

| 경로 | 내용 |
|---|---|
| `chess-engine-loop/` | 본 벤치마크. 과제 명세(`TASK.md`), 수트 정의(`suites.json`), 생성 엔진 전량, 결과 리포트 |
| `fog-chess-loop/` | 불완전정보(fog-of-war) 변형 벤치마크. 외부 라이브러리 없이 자체 구현 |
| `runners/` | 실행·채점 러너 (`chess_engine_loop.py`, `fog_chess_loop.py`) |

**먼저 볼 파일:** [`chess-engine-loop/results_20260524.md`](chess-engine-loop/results_20260524.md) ·
[`fog-chess-loop/results_20260605.md`](fog-chess-loop/results_20260605.md)

## 설계에서 신경 쓴 지점

**1. 베껴서 이긴 결과 배제**
후보는 표준 라이브러리만 쓸 수 있고, 프롬프트로 Stockfish·python-chess·Sunfish·TSCP 등
기존 엔진 소스의 참조/복사/변형을 금지합니다. 여기서 그치지 않고 **정적 검사로**
Stockfish 언급, `import chess`, 알려진 엔진 소스 마커를 탐지해 해당 결과를 채점에서 제외합니다.
Stockfish는 상대·평가자로만 쓰입니다.

**2. 루프 구조 3종을 동일 조건에서 비교**
- `one_shot` — 한 번 작성, 숨은 평가자가 채점
- `hidden_eval_loop` — 2라운드에 **점수 피드백만** 전달 (이전 코드 없음)
- `cumulative_hidden_eval_loop` — 점수 피드백 **+ 이전 엔진 코드** 전달

무엇이 성능을 올리는지 분리해서 보려면 피드백 채널을 다르게 준 구조를
같은 조건에 놓고 비교해야 한다고 판단했습니다. 산출물 해시를 고정해 재현성을 확보했습니다.
(`chess-engine-loop/generated_engines/20260524/MANIFEST.json`)

**3. 숨겨진 정보 접근 탐지 (fog-of-war)**
관측 정보만 받아야 하는 에이전트가 `canonical_board`·`full_board`·전체 FEN·숨은 합법수에
접근하지 못하도록 계약을 두고, **보이지 않는 적 퀸의 위치가 다른 두 보드가 동일한 관측으로
직렬화되는지** 검사해 정보 누출을 테스트합니다.

## 평가 설정 (2026-05-24 기준)

- 후보 모델: `gpt-5.4-mini low`, `gpt-5.5 low`
- 상대: Stockfish `UCI_Elo=1320`, depth 1 / 후보 `go movetime 20` / 최대 40플라이
- 결과 행당 16국, Jeffreys-smoothed W/D/L 점수로 Elo 추정
- 수트: `opening_gauntlet`(오프닝 4포지션 양색), `advantage_conversion`(우세 전환 4포지션 양색)

## 재현

```bash
cd chess-engine-loop && ./reproduce.sh    # 별도 Stockfish 바이너리 필요
```

## 관련 저장소

- [loop-evolution](https://github.com/wlsalswo14/loop-evolution) — 여기서 얻은 루프 비교 결과를 자가 진화 + 승격 계약으로 확장
- [primus](https://github.com/wlsalswo14/primus) — 하네스와 도메인을 분리해 다중 도메인 재사용이 가능하게 재설계
