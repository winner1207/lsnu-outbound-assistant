# 乐师对外教学助手

乐山师范学院对外教学助手：上传乐山相关图片，校本术语锁定后生成中英日讲解，并支持多轮对话。

本期只做 Web。App / 小程序预留。赛道 4（AI 辅助编程与智能体开发）。

## 仓库

- 目标与范围：系统目标.md
- 视觉：rand/（校徽与配色来自 [lsnu.edu.cn](https://www.lsnu.edu.cn/)）
- 模型探测：scripts/test_llm.py

## 本地

`ash
cp .env.example .env   # 填入 LLM_API_KEY
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/test_llm.py
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
`

.env 不要提交。

## 部署

阿里云 ECS，nginx 反代 80 -> 127.0.0.1:8000。

`ash
python scripts/deploy_remote.py
`

验收地址：http://<公网IP>/ （安全组需放行 80）。
