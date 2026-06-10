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

