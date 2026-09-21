#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: config.py
作者: 高帅舟
项目: 智租顾问（多智能体+RAG租房咨询系统）
创建日期: 2026/1/17
描述: 
"""

import os
import importlib.util

# 项目根目录
project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def _load_local_keys():
    """从 config_local/keys.py 加载本地密钥（该目录已被 .gitignore 排除）"""
    keys_path = os.path.join(project_root, 'config_local', 'keys.py')
    if not os.path.exists(keys_path):
        return None
    spec = importlib.util.spec_from_file_location('local_keys', keys_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_local_keys = _load_local_keys()

# 生产环境
# env = "prod"
# 测试环境
env = "test"
# 开发环境
# env = "dev"
# 预生产环境
# env = "pre_prod"



#定义配置文件
class Config:

    def __init__(self):
        # 大模型配置（密钥从 config_local/keys.py 或环境变量读取）
        # 优先级：环境变量 > config_local/keys.py > 公共默认端点（DashScope）
        # 私有网关地址写在 config_local/keys.py 中，不会上传到开源仓库
        self.base_url = os.getenv("DASHSCOPE_BASE_URL", "") or (
            getattr(_local_keys, 'DASHSCOPE_BASE_URL', '') if _local_keys else ""
        ) or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "") or (
            getattr(_local_keys, 'DASHSCOPE_API_KEY', '') if _local_keys else ""
        )
        self.model_name = os.getenv("DASHSCOPE_MODEL", "") or (
            getattr(_local_keys, 'DASHSCOPE_MODEL', '') if _local_keys else ""
        ) or "qwen-plus"
        # 轻量模型 (qwen-turbo): 模型路由策略下, 闲聊等低复杂度意图走便宜低延迟模型
        self.model_name_light = os.getenv("DASHSCOPE_MODEL_LIGHT", "") or (
            getattr(_local_keys, 'DASHSCOPE_MODEL_LIGHT', '') if _local_keys else ""
        ) or "qwen-turbo"

        # 数据库配置（密码从 config_local/keys.py 或环境变量读取）
        self.host = os.getenv("MYSQL_HOST", 'localhost')
        self.user = os.getenv("MYSQL_USER", 'root')
        self.password = os.getenv("MYSQL_PASSWORD", "") or (
            getattr(_local_keys, 'MYSQL_PASSWORD', '') if _local_keys else ""
        )
        self.database = 'rental'

        # 日志配置 - 统一输出到 Agent/logs/zhizu_advisor.log
        self.log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'zhizu_advisor.log')


        self.intent = {
            "house": "HouseQueryAssistant",
            "poi": "PoiQueryAssistant",
            "metro": "MetroQueryAssistant",
            "recommend": "RecommendQueryAssistant",
            "legal": "LegalQASystem",
            "chat": "ChatLLM"
        }

        self.temperature = 0.1

        # 是否启用大模型二次总结：True 时代理返回结果再走一次LLM润色（更自然但更慢），
        # False 时直接返回代理的结构化结果（更快，适合查询类问题）。查询太慢建议保持 False。
        self.use_llm_summary = False

        # 是否启用租房知识普及：True 时 house 意图查询房源后，自动附加 RAG 检索的租房常识（带引用）
        self.enable_rental_tips = True


    def get_mysql_config(self,env):
        """
        通过不同的环境获取不同的数据库配置
        :return:
        """
        if env == 'prod':
            # 数据库配置 生产
            self.host = os.getenv("MYSQL_HOST", 'localhost')
            self.user = os.getenv("MYSQL_USER", 'root')
            self.password = os.getenv("MYSQL_PASSWORD", "") or (
                getattr(_local_keys, 'MYSQL_PASSWORD', '') if _local_keys else ""
            )
            self.database = 'rental'
        elif env == 'dev':
            # 数据库配置 开发
            self.host = os.getenv("MYSQL_HOST", 'localhost')
            self.user = os.getenv("MYSQL_USER", 'root')
            self.password = os.getenv("MYSQL_PASSWORD", "") or (
                getattr(_local_keys, 'MYSQL_PASSWORD', '') if _local_keys else ""
            )
            self.database = 'rental'
        elif env == 'test':
            # 数据库配置 测试
            self.host = os.getenv("MYSQL_HOST", 'localhost')
            self.user = os.getenv("MYSQL_USER", 'root')
            self.password = os.getenv("MYSQL_PASSWORD", "") or (
                getattr(_local_keys, 'MYSQL_PASSWORD', '') if _local_keys else ""
            )
            self.database = 'rental'
        else:
            # 数据库配置 预生产
            self.host = os.getenv("MYSQL_HOST", 'localhost')
            self.user = os.getenv("MYSQL_USER", 'root')
            self.password = os.getenv("MYSQL_PASSWORD", "") or (
                getattr(_local_keys, 'MYSQL_PASSWORD', '') if _local_keys else ""
            )
            self.database = 'rental'

        return self.host, self.user, self.password, self.database


if __name__ == '__main__':
    print(Config().log_file)
    print(Config().get_mysql_config(env))
    # ('localhost', 'root', 'root', 'travel_rag')
    # ('localhost', 'root2', 'root2', 'travel_rag')