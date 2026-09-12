# 乐师对外教学助手

乐山师范学院对外教学助手：上传乐山相关图片，校本术语锁定后生成中英日讲解，并支持多轮对话。

本期只做 Web。App / 小程序预留。赛道 4（AI 辅助编程与智能体开发）。

## 仓库

- 目标与范围：`系统目标.md`
- 视觉：`brand/`（校徽与配色来自 [lsnu.edu.cn](https://www.lsnu.edu.cn/)）
- 模型探测：`scripts/test_llm.py`

## 本地

```bash
cp .env.example .env   # 填入 LLM_API_KEY
python scripts/test_llm.py
```

`.env` 不要提交。
