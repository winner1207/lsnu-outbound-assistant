# 乐师对外教学助手

乐山师范学院对外教学助手。上传图片或输入专名，按校本术语生成七语讲解，支持多轮对话。

## 运行

```
cp .env.example .env
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 部署

```
python scripts/deploy_remote.py
```
