# V3 lite 분리 기록

## 출발점

- 원본: `V3 lite/chess-package-evolution`
- 이관 시점 상태: R16 완료, 정체 2회
- 챔피언: `package_de8d36210d4b8f49`
- 챔피언 구조: `loop_c2081087024ecb8e`
- 챔피언 승격 라운드: R14

## 처리 내용

1. 원본 작업공간 1,126개 파일을 비파괴 복사했다.
2. 복사 직후 상대 경로별 SHA-256을 비교했고 차이는 0개였다.
3. 코드, 실험, 정책, 벤치마크, 최초 입력을 별도 경계로 나눴다.
4. `ouroboros_v3lite` 런타임 import를 로컬 `platform` 어댑터로 교체했다.
5. 활성 상태와 이력에서 이전 위치를 가리키는 115개 JSON/JSONL 파일의 경로만 기계적으로 변환했다.
6. 변경 전후 파일 해시는 `migration/relocation-v3-lite-r16.json`에 기록했다.
7. 기존 ChessBench 결과 캐시 120개를 해시 차이 없이 새 작업공간으로 복사했다.
8. 동결 contract hash는 유지하면서 실제 결과 캐시만 새 위치를 쓰도록 어댑터를 분리했다.

과거 benchmark receipt와 archive 안의 `source_benchmark_receipt_path`, 그리고 동결 케이스의
`metadata.result_dir`에 남은 V3 lite 문자열은 당시 평가 출처와 contract identity를 증명하는
메타데이터이므로 수정하지 않았다. 현재 캐시의 실제 읽기·쓰기 경로로 사용되지 않는다.

## 이전 폴더 정책

`V3 lite/chess-package-evolution`은 삭제하거나 덮어쓰지 않았다. 새 공식 실행 위치는
`Ouroboros/loop-evolution`이며, 이전 위치는 이관 전 상태를 복구할 수 있는 읽기 전용 백업이다.
