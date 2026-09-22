# 识景译韵-多语言智能解说系统

乐山师范学院多语言智能解说。上传图片或输入专名，按校本术语生成七语讲解，支持多轮对话。

## 运行

```
cp .env.example .env
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 部署

生产是 HTTPS git 仓库。本地提交并 `git push origin main` 后：

```
python scripts/deploy_remote.py
```

机上等价命令：`bash /opt/lsnu-outbound-assistant/deploy/git_pull.sh`。
