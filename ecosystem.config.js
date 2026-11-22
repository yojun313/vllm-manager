// vLLM Manager 웹 관리 화면을 PM2 로 상시 실행한다 (선택 사항. 보통은 `./vllm server up` 또는 `./vllm server enable` 로 충분하다).
//
//   sg docker -c "pm2 start ecosystem.config.js"
//
// - 관리 서버는 docker 를 쓰므로 pm2 데몬이 docker 그룹 권한을 가져야 한다.
// - watch 는 코드(app/, run.py)와 설정(.env) 만 본다. 폴더 전체를 보면 파이썬이 __pycache__ 에 .pyc 를 쓰는 것만으로
//   기동 중 재시작이 연달아 걸린다. 재시작돼도 진행 중인 다운로드·모델 기동은 끊기지 않는다(작업은 서버와 분리 실행).
// - 웹에서 설정을 저장하면 .env 가 바뀌어 자동으로 재시작된다.
const path = require("path");

const root = __dirname;
const dir = path.join(root, "server");

module.exports = {
  apps: [
    {
      name: "vllm",
      cwd: dir,
      script: path.join(dir, "start.sh"),
      interpreter: "bash",
      env: { PYTHONUNBUFFERED: "1", BUILDKIT_PROGRESS: "plain" },
      stop_exit_codes: [78],
      restart_delay: 10000,
      watch: [
        path.join(dir, "app"),
        path.join(dir, "run.py"),
        path.join(dir, "start.sh"),
        path.join(dir, ".env"),
        path.join(root, ".env"),
      ],
      ignore_watch: ["**/__pycache__/**", "**/*.pyc", ".venv", "data"],
      watch_delay: 1000,
      time: true,
    },
  ],
};
