# 自定义的 日志工具类.
# 统一输出到 Agent/logs/zhizu_advisor.log

# 导包
import logging
import os

# 计算统一日志文件路径: Agent/logs/zhizu_advisor.log
# logger.py 位于 Agent/legal_qa/base/，向上三级到 Agent/
_agent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log_file = os.path.join(_agent_dir, 'logs', 'zhizu_advisor.log')


# 封装日志配置函数 -> 可重复使用的双输出日志.
def setup_logger(log_file=log_file):
    """
    创建并返回日志记录器, 支持日志同时输出到控制台和文件, 且避免重复添加处理器.
    统一使用 zhizu_advisor 日志名称, 与主项目共享同一个日志文件.
    """
    # 1. 确保日志目录存在.
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 2. 创建日志记录器对象 -> 统一管理日志处理器, 并设置日志级别.
    logger = logging.getLogger('zhizu_advisor')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # 7. 为日志记录器添加处理器, 核心: 判断处理器是否存在, 避免多次调用函数导致重复添加.
    if not logger.handlers:
        # 3. 创建控制台处理器 -> 用于将日志输出到控制台.
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 4. 创建文件处理器 -> 用于将日志输出到文件.
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)

        # 5. 创建日志输出格式, 即: 时间戳 - 日志器名称 - 日志级别 - 日志内容
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # 6. 为两个处理器分别绑定日志格式.
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # 7. 添加处理器到日志记录器中.
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    # 8. 返回日志记录器.
    return logger


# 初始化日志器 -> 项目启动时自动执行, 其它模块导入此logger日志器即可直接使用.
logger = setup_logger()
