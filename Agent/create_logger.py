#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: create_logger.py
作者: ZZS
项目: LlmProject
创建日期: 2026/2/4
描述: 
"""
import logging
import os

from Agent.config import Config


def setup_logger(name, log_file='logs/app.log'):
    # 创建日志文件夹
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 获取日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    # 防止重复输出的关键！
    logger.propagate = False

    # 定义日志格式
    formatter = logging.Formatter('%(name)s - %(asctime)s - %(levelname)s - %(message)s')

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)  # 每个日志处理器可以单独设置日志级别，但是这个日志级别必须高于或等于处理器级别

    # 创建文件处理器
    file_handler = logging.FileHandler(filename=log_file, encoding="utf-8", mode="a")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # 将处理器添加到日志记录器中
    if not logger.handlers:  # 先进行判断，再进行添加。避免重复添加处理器
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger

logger = setup_logger('zhizu_advisor', Config().log_file)