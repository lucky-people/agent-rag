# Changelog

本项目所有重要变更均记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 即将推出
- CI/CD 自动化质量门（GitHub Actions：编译检查 + 单元测试 + SQL 安全回归）
- 多意图并行调度：一次提问多个意图时，子 Agent 调用并发执行，总延迟 ≈ 最慢意图
- 编排可观测性：RecommendAgent 编排的子调用（域/状态/耗时）在链路追踪面板独立展示

## [1.0.0] - 2026-09-15

### 新增
- 多智能体协作：House / Metro / Poi / Recommend 四个子智能体，通过 A2A 协议互联
- RecommendAgent 编排器：复杂跨域问题（如"1号线附近2000以下房源"）自动拆解为多域子任务，并行调用子智能体后汇总
- 双引擎架构：结构化数据查询（A2A + MCP）与法律知识问答（RAG）并行双路线
- BERT 意图分类 + 关键词兜底两级路由
- RAG 检索：BM25 + 稠密向量混合检索 + BGE Reranker
- 合同审查：支持上传租房合同，AI 提取风险点
- 用户系统：注册 / 登录 / 偏好画像 / 房源收藏 / 多维度对比
- SSE 流式输出 + 房源卡片渐进渲染 + 智能体链路追踪面板
- Docker 一键启动（MySQL + Redis + Milvus）与种子演示数据

### 安全加固
- 密钥统一收敛至 `config_local/`（被 .gitignore 排除），代码只读环境变量
- SQL 只读白名单：MCP 层仅允许 SELECT/WITH，拦截写操作与危险语句
- 移除爬虫中的滑块破解 / 反自动化检测代码，改为合规开源版
- 移除代码中硬编码的数据库密码与私有 API 端点
- 错误信息脱敏：不再向用户透传内部异常（路径 / 地址 / 堆栈）

### 可靠性
- 子 Agent / MCP 调用统一 15s 超时，挂起不再无限阻塞
- 区分"连接错误"与"SQL 错误"：基础设施故障直接失败，不再误当 SQL 错误白烧 LLM 调用
- 子 Agent 不可用时自动降级为 LLM 兜底回复
- 会话 TTL 过期清理（1 小时）+ 历史写入加锁

### 性能
- 闲聊路线改为 LLM 真流式（astream 逐 token 推送），首字延迟显著降低
- 高频 FAQ 走 Redis 缓存，响应快约 5 倍

### 重构
- 4 个 A2A server 收敛为 `Text2SqlAgentServer` 基类 + 子类（消除约 300 行重复代码）
- 修复 recommend server schema 字段漂移（补全 orientation / floor）

### 可复现性
- `docker-compose.yml`：MySQL / Redis / Milvus 一键启动
- `Agent/sql/seed_data.sql`：演示种子数据（52 房源 / 15 地铁站 / 15 POI / 7 天天气）
- `Agent/start.sh`：Linux / macOS 启动脚本；`启动系统.bat` 支持 `ZHIZU_PYTHON` 环境变量
- `requirements.txt`（CPU）与 `requirements-gpu.txt`（CUDA）拆分
- 实验数据集（data/）与结果图（results/）纳入版本管理

### 文档
- 重写 README：双引擎架构图、核心流程、目录架构、快速开始
- 新增 LICENSE（MIT）、.gitignore、演示视频（B 站）

[1.0.0]: https://gitee.com/gao-shuaizhou/zhizu-advisor/releases/tag/v1.0.0
