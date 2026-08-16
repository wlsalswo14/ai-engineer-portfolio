# Vendored evaluator sources

이 디렉터리는 **다른 프로젝트에서 가져와 동결한 채점 코드**입니다. 여기 있는 파일은 직접 수정하지 않습니다.

## 왜 여기 있나

이전에는 `config/domains/chess.json`의 `ouroboros_source`가 가리키는 외부 체크아웃
(`Ouroboros/loop-evolution/src`)을 평가 시점에 `sys.path`에 끼워 넣어 import 했습니다.

그 결과 Primus가 "동결된 평가 계약"이라고 부르던 것이 실제로는 **다른 프로젝트의 가변 작업
트리를 실시간으로 따라갔습니다.** 그 트리에 커밋되지 않은 수정이 쌓이면 Primus의 체스 점수는
조용히 다른 기준으로 매겨지고, 라운드 간 비교가 무효가 됩니다.

이제 소스는 이 트리 안에 있고, import 전에 `VENDOR.json`의 SHA-256과 대조합니다.

## 내용물

`ouroboros-loop-evolution` 0.2.0, 커밋 `52409d5` 기준 **바이트 그대로**입니다.

| 파일 | 역할 |
|---|---|
| `loop_evolution/platform/evaluation/chessbench.py` | `ChessBench100Scorer` — 실제 채점기 |
| `loop_evolution/platform/domain.py` | `TaskCase` (나머지 dataclass는 미사용) |
| `loop_evolution/platform/common.py` | `content_hash`, `freeze_mapping` |
| `loop_evolution/platform/runtime/answers.py` | `extract_final_answer` |

패키지 이름을 `loop_evolution` 그대로 둔 것은 의도적입니다. import 문을 고치지 않아야
상류와 해시가 정확히 일치하고, 재벤더링이 `cp` + 해시 재계산으로 끝납니다.

## 사용법

```python
from primus.vendor import activate
activate("chessbench-evaluator")          # 해시 검증 후 sys.path 최우선에 삽입
from loop_evolution.platform.evaluation.chessbench import ChessBench100Scorer
```

`activate()`는 검증에 실패하면 `IntegrityError`를 던지고 import를 진행하지 않습니다.
`primus doctor`가 매번 `verify()`를 호출하므로 라운드 시작 전에 드리프트가 잡힙니다.

## 재벤더링 절차

상류 채점기를 의도적으로 갱신할 때만 수행합니다. **진행 중인 계보의 점수 비교가 깨지므로,
새 protocol id를 부여하고 과거 라운드를 재해석하지 마십시오.**

1. 상류 저장소를 원하는 커밋으로 체크아웃하고 `git status`가 clean인지 확인
2. `VENDOR.json`의 `files` 목록에 있는 경로를 그대로 덮어쓰기
3. 매니페스트 재생성 (해시와 `upstream.commit`, `vendored_on` 갱신)
4. `python -m primus.cli doctor` 와 `pytest tests/test_vendor_freeze.py` 통과 확인
