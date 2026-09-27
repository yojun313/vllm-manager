// vLLM 관리 웹 서버(admin_server, 포트 8021)를 pm2 로 상시 실행한다.
//
//   sg docker -c "pm2 start ecosystem.config.js"
//
// - 관리 서버는 docker 를 쓰므로 pm2 데몬이 docker 그룹 권한을 가져야 한다 (README "웹 관리 화면" 참고).
// - watch 는 코드(app/, run.py)와 .env 만 본다. 폴더 전체를 보면 파이썬이 __pycache__ 에 .pyc 를 쓰는 것만으로
//   기동 중 재시작이 연달아 걸린다. 재시작돼도 진행 중인 다운로드·모델 기동은 끊기지 않는다(작업은 서버와 분리 실행).
const path = require("path");

const dir = path.join(__dirname, "admin_server");

module.exports = {
  apps: [
    {
      name: "vllm",
      cwd: dir,
      script: "run.py",
      interpreter: path.join(dir, ".venv", "bin", "python"),
      watch: ["app", "run.py", ".env"],
      ignore_watch: ["**/__pycache__/**", "**/*.pyc", ".venv", "data"],
      watch_delay: 1000,
      time: true,
    },
  ],
};
