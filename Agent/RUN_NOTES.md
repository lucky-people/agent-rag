# 系统数据与运行说明

> 本说明适用于「基于多智能体与RAG的智能租房咨询系统」当前版本。
> 完整项目介绍（架构、安装、启动）请见项目根目录 [README.md](../README.md)。

## 1. 意图与数据对应关系

| 意图 | 说明 | 示例 | A2A 代理 | MCP 端口 | 数据表 |
|------|------|------|----------|---------|--------|
| `house` | 房源查询 | 金水区有没有2000元以下的整租房？离地铁站近的房源有哪些 | HouseQueryAssistant :5006 | 8004 | `house_listing` |
| `poi` | 周边探索 | 二七广场附近有什么好吃的？1号线沿线有哪些景点？ | PoiQueryAssistant :5007 | 8005 | `poi_data` |
| `metro` | 交通出行 | 郑州东站坐几号线？离我最近的地铁站在哪 | MetroQueryAssistant :5008 | 8006 | `metro_station` / `poi_data` |
| `recommend` | 综合推荐 | 1号线附近2000以下的房源有哪些？金水区离地铁近的景点有哪些？ | RecommendQueryAssistant :5009 | 8007 | `house_listing` / `poi_data` / `metro_station` |
| `legal` | 法律问答 | 房东不退押金怎么办？帮我审查这份合同 | LegalQASystem（RAG） | — | 法律知识库（Milvus）/ FAQ（MySQL） |
| `chat` | 通用对话 | 其它问题 | ChatLLM | — | — |

## 2. 数据来源（Agent/数据库操作 目录）

数据存放在 **`rental`** 数据库（`Agent/config.py` 指向该库）：

- `house_listing` —— 贝壳租房郑州站房源（`data_collection/crawler.py`）
- `poi_data` —— 高德POI：旅游景点/公园广场/医疗保健/住宿服务/餐饮服务
- `metro_station` —— 高德地铁站（`数据库操作/fetch_metro.py`）
- `poi_data` 的最近地铁字段由 `数据库操作/update_poi_metro.py` 关联补齐
- 法律问答数据：`legal_qa/rag_qa/data/` 下民法典/刑法/劳动法/民事诉讼法等公开法律文本（docx/pdf），经 `ingest_rental_laws.py` 入库

> 表结构汇总见 `Agent/sql/rental_schema.sql`。请先确认本机 MySQL 中 `rental` 库已建好并有数据。

## 3. 启动步骤

### 方式一：一键启动（推荐）

双击运行 `Agent/start.bat`（或 `Agent/` 目录下 `python start.py`），启动器会依次完成：

1. **预检**：Python / 中间件（MySQL 3306、Redis 6379、Milvus 19530）/ 端口冲突，问题一次性列清
2. **分组拉起**：MCP 工具服务器（4）→ A2A 智能体服务器（5）→ Web 前端（8501），组间等待就绪，避免并发抢中间件导致部分服务起不来
3. **健康轮询**：每个服务 TCP 探测，最长等待 60s，输出 ✅/❌ 汇总表
4. 自动打开浏览器 http://localhost:8501（管理员看板 `/admin/dashboard`，默认 admin/admin123）

辅助命令：

- `python start.py --status`：查看中间件与各服务端口状态
- `python start.py --stop`：停止由启动器拉起的全部后台服务
- 启动日志：`Agent/logs/startup/<服务名>.log(.err.log)`（起不来看日志尾部即知原因）

> 中间件不在线时预检会明确提示「请先启动: docker compose up -d」；本机 MySQL（phpstudy）需先启动 MySQL 服务。

### 方式二：手动逐个启动（按依赖顺序）

1. MCP 服务器（在 `Agent/` 目录下执行）：
   - `python -m mcp_server.mcp_house_server`（8004）
   - `python -m mcp_server.mcp_poi_server`（8005）
   - `python -m mcp_server.mcp_metro_server`（8006）
   - `python -m mcp_server.mcp_recommend_server`（8007）
2. A2A 代理服务器：
   - `python -m a2a_server.house_server`（5006）
   - `python -m a2a_server.poi_server`（5007）
   - `python -m a2a_server.metro_server`（5008）
   - `python -m a2a_server.recommend_server`（5009）
3. Web 前端：`python -m web_server`（http://localhost:8501）

## 4. 主要入口文件

| 入口 | 路径 | 用途 |
|------|------|------|
| Web 系统入口（推荐） | `Agent/web_server.py` | 完整系统：A2A 智能体 + RAG 法律问答双路线，提供网页界面 |
| 法律问答命令行入口 | `Agent/legal_qa/new_main.py` | RAG 法律问答系统的命令行演示（不启动 Web） |
| MySQL FAQ 演示入口 | `Agent/legal_qa/mysql_qa/main.py` | 仅演示 MySQL + BM25 FAQ 检索链路 |

> 日常使用请通过 Web 入口；后两者为子系统的独立演示脚本，供调试与学习。
