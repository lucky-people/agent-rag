# 🏠 基于多智能体与RAG的智能租房咨询系统

一个面向郑州本地租房场景的 **多智能体协作 + 检索增强生成（RAG）** 智能问答系统。用户通过自然语言咨询租房相关问题，系统自动识别意图，路由到对应的子智能体（房源查询 / 地铁出行 / 周边探索 / 综合推荐），并内置法律问答 RAG 引擎，支持租房合同审查与高频租房常识问答。

> 本系统为毕业设计项目，融合了 **多智能体（A2A 协议）+ MCP 工具调用 + RAG（BM25 混合检索 + BGE Reranker）+ BERT 意图分类** 等主流技术栈。

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🏠 房源查询 | 按区域 / 租金 / 户型 / 朝向 / 楼层等条件检索整租、合租房源，支持详情跳转 |
| 🚇 交通出行 | 查询地铁线路、站点，关联房源与地铁距离 |
| 📍 周边探索 | 查询景点、餐饮、医院等 POI 信息 |
| ⭐ 综合推荐 | 复杂查询（如"1号线附近2000以下房源"）自动调用多个子智能体协作 |
| ⚖️ 法律问答 RAG | 租房合同审查（上传合同文件）、押金纠纷、退租责任等法律常识问答 |
| 💬 通用对话 | 非业务类提问直接由大模型回答 |
| 🔍 双路线检索 | 高频问题走 Redis 缓存（快 5 倍），其余走 BM25 + 向量 + Reranker 混合检索 |
| 🎯 意图识别 | 微调 BERT 模型对查询进行意图分类，支持多意图组合 |
| 🔗 智能体链路追踪 | 前端可视化展示每次提问调用的智能体、顺序与耗时 |
| ⚡ 流式响应 | SSE 流式输出 + 房源卡片渐进式渲染 |

---

## 🏗️ 系统架构

```
前端展示层（新版网页.html · SSE 流式输出 · 房源卡片 · 收藏对比）
        │ HTTP + SSE
主服务层（Agent/web_server.py · 意图分类 · 路由分发 · 会话管理）
        │ A2A 协议
多智能体协作层（a2a_server/）
   HouseAgent · MetroAgent · PoiAgent · RecommendAgent · LegalQA
        │ MCP 工具调用
工具执行层（mcp_server/）
   mcp_house · mcp_metro · mcp_poi · mcp_recommend
        │ SQL / 向量检索
数据存储层
   MySQL（房源/POI/地铁/法律FAQ） · Milvus（向量库） · Redis（缓存） · DashScope LLM · BGE Reranker
```

**技术要点：**

- **多智能体协作**：基于 `python-a2a` 实现 Agent 网络，每个子智能体独立负责一类数据查询，通过 A2A 协议互联，复杂问题自动编排多个智能体。
- **MCP 工具层**：每个智能体背后挂载 MCP（Model Context Protocol）服务器，统一封装 SQL 查询能力。
- **RAG 混合检索**：BM25 关键词检索 + BGE-M3 稠密/稀疏向量检索加权融合，再由 BGE Reranker 重排序，兼顾召回率与精度。
- **BERT 意图分类**：基于 `bert-base-chinese` 微调的分类器，识别「通用知识 / 专业咨询」等意图并路由。
- **缓存加速**：高频租房常识问题存于 Redis，命中缓存时跳过完整 RAG 链路，响应快约 5 倍。

---

## 📁 目录结构

```
多智能体+RAG综合项目/
├── Agent/                          # 主系统代码
│   ├── web_server.py               # Web 后端入口（Flask，端口 8501）
│   ├── config.py                   # 配置（密钥读取自 config_local/，见下方说明）
│   ├── main_prompts.py             # 意图识别 / 各智能体总结提示词
│   ├── user_system.py              # 用户系统（收藏 / 历史记录）
│   ├── a2a_server/                 # 多智能体协作层（A2A 协议）
│   │   ├── house_server.py         #   房源查询智能体
│   │   ├── metro_server.py         #   地铁出行智能体
│   │   ├── poi_server.py           #   周边探索智能体
│   │   └── recommend_server.py     #   综合推荐智能体
│   ├── mcp_server/                 # 工具执行层（MCP 服务器）
│   │   └── mcp_house/metro/poi/recommend_server.py
│   ├── legal_qa/                   # 法律问答子系统
│   │   ├── base/                   #   基础配置与日志
│   │   ├── mysql_qa/               #   基于 MySQL 的 FAQ 检索（BM25 + Redis 缓存）
│   │   └── rag_qa/                 #   基于 Milvus 的 RAG（向量检索 + Reranker + BERT 意图分类）
│   ├── 数据库操作/                  # 数据采集脚本
│   │   ├── 爬虫.py                 #   贝壳租房郑州站房源爬虫
│   │   ├── fetch_metro.py          #   高德地铁站数据
│   │   └── update_poi_metro.py  #   POI 地铁关联补齐
│   ├── sql/rental_schema.sql       # 数据库表结构
│   ├── 新版网页.html                # 前端页面
│   └── 启动系统.bat                 # 一键启动脚本
├── 实验脚本/                        # 毕业设计实验（消融实验 + 意图评估）
│   ├── run_rag_ablation.py         #   RAG 检索策略消融实验（4 策略对比）
│   ├── run_intent_evaluation.py    #   BERT 意图分类评估
│   └── data/                       #   测试数据集
├── 数据集/                          # 爬取的数据
├── config_local/                   # ⚠️ 本地密钥目录（已被 .gitignore 忽略，不提交）
│   ├── config.ini                  #   MySQL / Redis / Milvus / LLM 真实配置
│   └── keys.py                     #   API Key / 数据库密码
├── requirements.txt                # Python 依赖清单
└── .gitignore
```

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- MySQL 8.0+（数据库 `rental`，含房源 / POI / 地铁 / FAQ 数据）
- Milvus 2.x 向量数据库（集合 `edurag_final`）
- Redis 6+（缓存）
- 可访问阿里云 DashScope（通义千问）的 API Key
- （可选）GPU：用于 BERT 分类 / BGE 向量模型，CPU 也可运行但较慢

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

> 建议使用 conda 创建虚拟环境：`conda create -n lang_env python=3.10`
> 如使用 OCR 文档入库功能，需额外安装可选依赖（见 requirements.txt 末尾注释）。

### 2. 配置密钥

项目所有真实密钥统一放在 `config_local/` 目录（该目录已被 `.gitignore` 忽略，不会上传到仓库）：

```
config_local/
├── config.ini     # MySQL/Redis/Milvus/LLM 配置
└── keys.py        # DASHSCOPE_API_KEY / AMAP_API_KEY / MYSQL_PASSWORD / REDIS_PASSWORD
```

1. 从仓库中复制模板文件（`Agent/config.py.example`、`Agent/legal_qa/config.ini.example`、`Agent/数据库操作/amap_key.example.py`）
2. 手动创建 `config_local/config.ini` 与 `config_local/keys.py`，填入你的真实密钥
3. 代码会自动从 `config_local/` 读取，无需设置环境变量

### 3. 初始化数据

1. 执行 `Agent/sql/rental_schema.sql` 建表
2. 运行 `Agent/数据库操作/爬虫.py` 爬取房源数据（或使用 `数据集/` 中已有的数据）
3. 运行 `Agent/ingest_rental_laws.py` / `Agent/ingest_rental_tips.py` 构建法律知识向量库

### 4. 启动系统

**方式一：一键启动（推荐）**

双击运行 `Agent/启动系统.bat`，自动依次启动 MCP 服务器 → A2A 智能体 → Web 前端。

**方式二：手动启动**

```bash
# 1. MCP 服务器（4 个）
python -m mcp_server.mcp_house_server      # 8004
python -m mcp_server.mcp_poi_server        # 8005
python -m mcp_server.mcp_metro_server      # 8006
python -m mcp_server.mcp_recommend_server  # 8007

# 2. A2A 智能体（4 个）
python -m a2a_server.house_server          # 5006
python -m a2a_server.poi_server            # 5007
python -m a2a_server.metro_server          # 5008
python -m a2a_server.recommend_server      # 5009

# 3. Web 后端
python -m web_server                        # http://localhost:8501
```

打开浏览器访问 **http://localhost:8501** 即可使用。

### 5. 入口文件说明

项目有多个可执行入口，各自职责不同：

| 入口 | 路径 | 用途 | 启动方式 |
|------|------|------|---------|
| **Web 系统入口（主）** | `Agent/web_server.py` | 完整系统：A2A 智能体 + RAG 法律问答 + 网页界面 | `python -m web_server`（在 Agent/ 下） |
| 法律问答命令行入口 | `Agent/legal_qa/new_main.py` | 不启动 Web，命令行体验 RAG 法律问答 | `python -m legal_qa.new_main`（在 Agent/ 下） |
| MySQL FAQ 演示入口 | `Agent/legal_qa/mysql_qa/main.py` | 演示 MySQL + BM25 + Redis FAQ 链路 | `python -m mysql_qa.main`（在 legal_qa/ 下） |

> 日常使用用 **Web 入口**；后两者是子系统独立演示脚本，供调试与学习。

---

## 💬 使用示例

| 用户提问 | 路由 |
|---------|------|
| 金水区有没有2000元以下的整租房？ | HouseQueryAssistant |
| 郑州东站坐几号线？ | MetroQueryAssistant |
| 二七广场附近有什么好吃的？ | PoiQueryAssistant |
| 1号线附近2000以下的房源有哪些？ | RecommendQueryAssistant（多智能体协作） |
| 房东不退押金怎么办？ | LegalQASystem（RAG） |
| 你好 / 谢谢 | ChatLLM（通用对话） |

---

## 🧪 实验脚本（毕设亮点）

`实验脚本/` 目录包含两组可复现的实验，可直接产出论文 / PPT 所需的图表：

1. **RAG 检索策略消融实验**（`run_rag_ablation.py`）
   - 对比：纯 BM25 / 纯稠密向量 / 混合检索 / 混合 + Reranker 四种策略
   - 指标：Recall@5、MRR、平均检索耗时
2. **意图分类与路由机制量化评估**（`run_intent_evaluation.py`）
   - 统计意图分类准确率、混淆矩阵、误分类案例分析

```bash
python 实验脚本/run_rag_ablation.py
python 实验脚本/run_intent_evaluation.py
```

---

## 📄 License

本项目基于 [MIT License](LICENSE) 开源。

---

## 🙏 致谢

- 数据来源：贝壳租房、高德地图开放平台（POI / 地铁）、法律法规公开文本
- 技术框架：LangChain、python-a2a、MCP、Milvus、Hugging Face Transformers
