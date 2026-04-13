const path = require("path");

// npx pm2 start ecosystem.config.js：cwd=本文件所在目录（项目根），便于 load_dotenv / env_file 找到 .env
module.exports = {
  apps: [{
    name: "coin-scanner",
    script: ".venv/bin/python",
    args: "main.py --serve",
    cwd: __dirname,
    // PM2 5.2+：把 .env 注入子进程环境；若启动报错可删掉本行，仍可依 main.py 的 load_dotenv 加载
    env_file: path.join(__dirname, ".env"),
    autorestart: true,
    max_restarts: 10,
    restart_delay: 5000,
    log_date_format: "YYYY-MM-DD HH:mm:ss",
    error_file: "logs/pm2-error.log",
    out_file: "logs/pm2-out.log",
    merge_logs: true,
  }]
};
