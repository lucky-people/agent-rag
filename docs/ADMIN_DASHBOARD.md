# 管理员数据看板（Observability Dashboard）

> **一句话**：把"系统跑得怎么样"变成可视化指标——请求耗时、路由分布、缓存命中、
> 成本观测、评估质量，且**详细统计仅管理员可见**（用户端保持原聊天界面）。

## 权限设计（管理员端 / 用户端）

| 端 | 入口 | 可见内容 |
| --- | --- | --- |
| 用户端 | `/`（新版网页.html） | 聊天 + 意图路由 + 协作链路追踪（不变） |
| 管理员端 | `/admin/dashboard` | 四层运行指标（下述） |

- 访问 `/admin/*`、`/api/admin/metrics` 未登录 → 302 跳登录页 / 401
- 登录用 **Flask Session**（Cookie 会话），凭据可配置（见下）

## 管理员凭据配置

优先级：环境变量 > `config_local/keys.py` > 内置默认（仅开发用，**生产必须改**）。

```python
# config_local/keys.py（已 gitignore，不会上传仓库）
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "your_strong_password"
FLASK_SECRET_KEY = "random-64-hex"   # 不配则每次重启随机(旧会话失效)
```

或环境变量：`ADMIN_USERNAME` / `ADMIN_PASSWORD` / `FLASK_SECRET_KEY`。

## 看板四层指标（对应 `Agent/metrics.py`）

| 层 | 指标 | 采集点 |
| --- | --- | --- |
| 技术层 | QPS / 平均耗时 / P50 / P99 / 错误数 | `process()` + 流式 `generate()` 出口 |
| 业务层 | 路由分布（chat/legal/agent/error）、意图分布（6类） | 同上，`intent_dist` 逐意图计数 |
| 缓存层 | RAG 答案缓存命中率（hit / hit_rate） | `legal_qa/new_main.py` 缓存命中分支 |
| 质量层 | 引用真实率（三策略）/ PASS-FAIL | 自动读取最新 `实验脚本/results/eval_report_*.json` |
| 成本层 | LLM 调用次数 / 估算成本（元） | 模型路由分支 `record_llm`（token 按字符估算） |

- 指标为**进程内存**累计（重启清零），适合演示/单实例；多实例可扩展 Redis 聚合（见"扩展"）。
- 耗时统计保留最近 1000 条计算分位数；P99 = 99% 请求耗时上界（越接近 P50 说明越稳定）。

## 路由

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/admin/login` | 登录页（表单校验） |
| GET | `/admin/logout` | 登出 |
| GET | `/admin/dashboard` | 看板页（ECharts，5s 自动刷新） |
| GET | `/api/admin/metrics` | 指标 JSON（登录后可用） |

## 本地验证

```powershell
python Agent/web_server.py        # http://localhost:8501
# 浏览器访问 http://localhost:8501/admin/dashboard
```

## 与评估回归门联动

质量层数据来自 `实验脚本/results/eval_report_*.json`（由 `eval_gate.py` 生成）。
跑一次 `python 实验脚本/eval_gate.py` 后，看板质量区即展示最新三策略引用真实率与 PASS/FAIL。

## 扩展方向（面试可讲）

- **持久化**：指标写入 Redis（按分钟聚合），重启不丢、支持多实例聚合。
- **告警**：P99 超阈值 / 错误率突增 → 企业微信/钉钉 webhook（与评估门 FAIL 同一套策略）。
- **成本精确化**：当前按字符估算 token；接 DashScope usage 字段后可精确计量。
