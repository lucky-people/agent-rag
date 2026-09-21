# 贡献指南 Contributing

感谢你愿意为 **智租顾问（zhizu-advisor）** 贡献代码！请花两分钟阅读本指南，让协作更顺畅。

## 项目简介

面向郑州本地租房场景的 **多智能体协作 + RAG** 智能问答系统。输入自然语言，系统自动识别意图、编排多个子智能体协同查询（房源 / 地铁 / 周边 / 综合推荐），并内置基于 RAG 的法律问答引擎。

## 环境准备

```bash
# 1. 克隆仓库
git clone https://gitee.com/gao-shuaizhou/zhizu-advisor.git
cd zhizu-advisor

# 2. 创建虚拟环境（Python 3.10+）
conda create -n lang_env python=3.10
conda activate lang_env

# 3. 安装依赖（CPU 版；GPU 用户追加 requirements-gpu.txt）
pip install -r requirements.txt

# 4. 启动中间件（Docker）
docker compose up -d

# 5. 导入表结构与演示数据
docker exec -i zhizu-mysql mysql -uroot -pzhizu123 < Agent/sql/rental_schema.sql
docker exec -i zhizu-mysql mysql -uroot -pzhizu123 < Agent/sql/seed_data.sql

# 6. 配置密钥：复制 *.example 模板到 config_local/ 并填入真实密钥
```

## 开发流程

1. **Fork 本仓库**，从 `main` 分支创建你的功能分支：
   ```bash
   git checkout -b feat/my-feature
   ```
2. **编写代码**，遵循现有代码风格（PEP 8，中文注释，函数带 docstring）。
3. **编写/更新测试**：所有核心逻辑改动必须附带单元测试（`tests/` 目录）。
4. **本地跑通测试**（确保零失败）：
   ```bash
   python -m unittest discover tests -v
   ```
5. **提交并推送**，提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：
   ```
   feat: 新增XX功能
   fix: 修复XX问题
   refactor: 重构XX模块
   docs: 更新文档
   ```
6. **发起 Pull Request**，描述改动内容与测试结果。

## 代码规范

| 项 | 要求 |
|---|---|
| Python 版本 | 3.10+ |
| 代码风格 | PEP 8 + 中文注释 |
| 提交信息 | Conventional Commits 格式 |
| 测试 | 核心逻辑必须带 `tests/` 下的单测 |
| 密钥 | **绝不**在代码或提交中写入密钥；一律走 `config_local/` 或环境变量 |
| 数据库访问 | 通过 MCP 层的 SQL 只读白名单，禁止直接拼接写操作 |

## 安全红线

- 禁止提交 `config_local/` 目录下的任何文件
- 禁止在代码中硬编码密码 / API Key / 私有端点
- MCP 层 SQL 必须通过 `validate_readonly_sql` 校验（仅 SELECT/WITH）
- 发现安全问题请**私信**仓库维护者，不要在 Issue 中公开

## 测试要求

测试文件放在 `tests/`，命名 `test_*.py`。现有测试覆盖：

- `test_format.py`：工具函数（SQL LIMIT 补充、JSON 解析、异常格式化）
- `test_intent_rules.py`：意图关键词兜底规则
- `test_core_logic.py`：SQL 只读白名单 / 基类三分支 / 编排降级

新增逻辑请参照上述模式补充对应测试。

## 提问与交流

- Bug / 功能建议：提交 [Issue](https://gitee.com/gao-shuaizhou/zhizu-advisor/issues)
- 使用问题：先看 [README](README.md) 与 [数据与运行说明](Agent/RUN_NOTES.md)
- 演示视频：B 站 [BV1queJ6qE7f](https://www.bilibili.com/video/BV1queJ6qE7f)
