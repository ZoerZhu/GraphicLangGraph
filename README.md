# GraphicLangGraph

中文可视化 LangGraph Agent 生成器 P0 原型。

## 结构

- `frontend/`：React + TypeScript + React Flow 画布
- `backend/`：FastAPI + Pydantic IR + LangGraph Python 源码生成
- `storage/projects/`：本地 JSON 项目数据
- `exports/`：导出的 ZIP 包
- `docs/`：产品和技术计划

## 本地启动

后端：

```powershell
cd backend
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --port 8000
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。

## 运行预览

编辑器顶部「运行」支持两种模式：

- 模拟运行：不调用模型或外部接口，只模拟路径、state 写入和分支选择。
- 真实运行：v1 支持 LLM、Retriever、Condition / AI Router 和 Direct Reply；需要先安装后端开发依赖，并配置对应模型供应商的环境变量，例如 `OPENAI_API_KEY`。
