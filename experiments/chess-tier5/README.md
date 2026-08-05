# Chess Tier-5 experiment

이 폴더는 범용 루프 진화 엔진의 첫 실험 인스턴스다. 설정, 활성 상태, 라운드 이력이 여기서만
결합된다. ChessBench 입력과 모델 정책은 루트 `resources`에 동결되어 있으며 `config.json`은
상대 경로로 이를 참조한다.

현재 R19까지 완료됐다. 이후 실행은 프로젝트 루트에서 `python run.py run-round`로 이어간다.

`workspace/benchmark-results`는 과거 결과 120개를 그대로 복사한 로컬 캐시다. 새 평가도 이 위치에
저장되며 V3 lite의 결과 폴더에는 쓰지 않는다.
