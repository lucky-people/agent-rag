# base 包初始化文件
# 说明: 统一使用以 Agent.legal_qa.base 为根的绝对导入, 不再手动修改 sys.path.

# 导入配置解析类, 用于: 读取项目配置.
from Agent.legal_qa.base.config import Config

# 导入初始化好的日志实例, 用于项目日志记录.
from Agent.legal_qa.base.logger import logger

__all__ = ["Config", "logger"]
