# 该脚本用于: 配置文件管理.
# 该脚本用于: 配置文件管理.

# 导包
import configparser                 # 导入配置文件解析库, 解析INI格式的配置文件.
import os                           # 导入路径操作模块


# todo 1.配置文件路径计算.
# 1. 获取当前文件的绝对路径.
current_file_path = os.path.abspath(__file__)
# print(f'current_file_path: {current_file_path}')    # D:\workspace\ai_30_bj\integrated_qa_system\base\config.py

# 2. 获取当前文件所在目录的绝对路径.
current_dir_path = os.path.dirname(current_file_path)
# print(f'current_dir_path: {current_dir_path}')      # D:\workspace\ai_30_bj\integrated_qa_system\base

# 3. 获取项目根目录的绝对路径
project_root = os.path.dirname(current_dir_path)
# print(f'project_root: {project_root}')                # D:\workspace\ai_30_bj\integrated_qa_system

# 4. 拼接配置文件(config.ini)的完整路径.
# 优先读取项目根目录下 config_local/config.ini（集中密钥目录，已被 .gitignore 排除）
whole_project_root = os.path.dirname(os.path.dirname(project_root))  # 整个项目根目录
config_file_path = os.path.join(whole_project_root, 'config_local', 'config.ini')
if not os.path.exists(config_file_path):
    # 兼容旧路径：Agent/legal_qa/config.ini
    config_file_path = os.path.join(project_root, 'config.ini')
# print(f'config_file_path: {config_file_path}')          # D:\workspace\ai_30_bj\integrated_qa_system\config.ini


# todo 2.配置解析类 -> 封装配置文件读取逻辑, 提供统一的配置参数访问接口.
class Config:
    # todo 2.1 初始化方法: 读取配置文件并解析各服务的配置参数.
    def __init__(self, config_file=config_file_path):
        # # 1. 创建配置文件解析器实例.
        # self.config = configparser.ConfigParser()
        # # 2. 读取配置文件 -> 根据传入的路径加载ini文件内容.
        # self.config.read(config_file, encoding='utf-8')
        #
        # # 3. 解析并存储各服务配置参数.
        # # 3.1 解析MySQL数据库配置.
        # self.MYSQL_HOST = self.config.get('mysql', 'host', fallback='localhost')
        # self.MYSQL_USER = self.config.get('mysql', 'user', fallback='root')
        # self.MYSQL_PASSWORD = self.config.get('mysql', 'password', fallback='')
        # self.MYSQL_DATABASE = self.config.get('mysql', 'database', fallback='subjects_kg')
        #
        # # 3.2 解析Redis数据库配置.
        # self.REDIS_HOST = self.config.get('redis', 'host', fallback='localhost')
        # self.REDIS_PORT = self.config.get('redis', 'port', fallback=6379)
        # self.REDIS_PASSWORD = self.config.get('redis', 'password', fallback='')
        # self.REDIS_DB = self.config.get('redis', 'db', fallback=0)
        #
        # # 3.3 解析日志配置.
        # # 日志文件路径: 从 [logger]节点的log_file键获取, 默认值为: logs/app.log
        # self.LOG_FILE = self.config.get('logger', 'log_file', fallback='logs/app.log')


        # 创建配置解析器，启用插值功能
        self.config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
        # 如果没有提供配置文件路径，则使用默认路径
        self.PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
        self.LOG_DIR = os.path.join(self.PROJECT_ROOT, 'logs')
        self.DATA_DIR = os.path.join(self.PROJECT_ROOT, 'rag_qa/data')
        self.MODELS_DIR = os.path.join(self.PROJECT_ROOT, 'rag_qa/models')
        self.EDU_DOCUMENT_LOADERS_DIR = os.path.join(self.PROJECT_ROOT, 'rag_qa/edu_document_loaders')

        if config_file is None:
            # 优先读取项目根目录下 config_local/config.ini（集中密钥目录）
            _whole_root = os.path.dirname(os.path.dirname(self.PROJECT_ROOT))
            _local_cfg = os.path.join(_whole_root, 'config_local', 'config.ini')
            if os.path.exists(_local_cfg):
                config_file = _local_cfg
            else:
                config_file = os.path.join(self.PROJECT_ROOT, 'config.ini')
        # 读取配置文件
        self.config.read(config_file, encoding='utf-8')

        # MySQL 配置
        # MySQL 主机地址
        self.MYSQL_HOST = os.getenv('MYSQL_HOST', self.config.get('mysql', 'host', fallback='localhost'))
        # MySQL 用户名
        self.MYSQL_USER = os.getenv('MYSQL_USER', self.config.get('mysql', 'user', fallback='root'))
        # MySQL 密码
        self.MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', self.config.get('mysql', 'password', fallback=''))
        # MySQL 数据库名
        self.MYSQL_DATABASE = os.getenv('MYSQL_DATABASE',
                                        self.config.get('mysql', 'database', fallback='laws_all'))

        # Redis 配置
        # Redis 主机地址
        self.REDIS_HOST = os.getenv('REDIS_HOST', self.config.get('redis', 'host', fallback='localhost'))
        # Redis 端口
        self.REDIS_PORT = int(os.getenv('REDIS_PORT', self.config.get('redis', 'port', fallback=6379)))
        # Redis 密码
        self.REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', self.config.get('redis', 'password', fallback=''))
        # Redis 数据库编号
        self.REDIS_DB = int(os.getenv('REDIS_DB', self.config.get('redis', 'db', fallback=0)))

        # Milvus 配置
        # Milvus 主机地址
        self.MILVUS_HOST = os.getenv('MILVUS_HOST', self.config.get('milvus', 'host', fallback='localhost'))
        # Milvus 端口
        self.MILVUS_PORT = os.getenv('MILVUS_PORT', self.config.get('milvus', 'port', fallback='19530'))
        # Milvus 数据库名
        self.MILVUS_DATABASE_NAME = os.getenv('MILVUS_DATABASE_NAME',
                                              self.config.get('milvus', 'database_name', fallback='laws_all'))
        # Milvus 集合名
        self.MILVUS_COLLECTION_NAME = os.getenv('MILVUS_COLLECTION_NAME',
                                                self.config.get('milvus', 'collection_name',
                                                                fallback='edurag_final'))

        # LLM 配置
        # LLM 模型名
        self.LLM_MODEL = self.config.get('llm', 'model', fallback='qwen-plus')
        # DashScope API 密钥
        self.DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY', self.config.get('llm', 'dashscope_api_key',
                                                                                fallback='记得改成你的密钥'))
        # DashScope API 地址
        self.DASHSCOPE_BASE_URL = self.config.get('llm', 'dashscope_base_url',
                                                  fallback='https://dashscope.aliyuncs.com/compatible-mode/v1')

        # 检索参数
        # 父块大小
        self.PARENT_CHUNK_SIZE = self.config.getint('retrieval', 'parent_chunk_size', fallback=1200)
        # 子块大小
        self.CHILD_CHUNK_SIZE = self.config.getint('retrieval', 'child_chunk_size', fallback=300)
        # 块重叠大小
        self.CHUNK_OVERLAP = self.config.getint('retrieval', 'chunk_overlap', fallback=50)
        # 检索返回数量
        self.RETRIEVAL_K = self.config.getint('retrieval', 'retrieval_k', fallback=5)
        # 最终候选数量
        self.CANDIDATE_M = self.config.getint('retrieval', 'candidate_m', fallback=2)

        # 应用配置
        # 有效来源列表（安全解析，避免 eval 执行任意表达式）
        import json as _json
        _raw = self.config.get('app', 'valid_sources', fallback='["ai", "java", "test", "ops", "bigdata"]')
        try:
            self.VALID_SOURCES = _json.loads(_raw)
        except Exception:
            self.VALID_SOURCES = ["ai", "java", "test", "ops", "bigdata"]
        # 客服电话
        self.CUSTOMER_SERVICE_PHONE = self.config.get('app', 'customer_service_phone', fallback='13112345678')

        # 日志文件路径
        self.LOG_FILE = os.path.join(self.LOG_DIR, 'app.log')

# 扩展: 创建Config类的实例.
config = Config()

# todo 3. 主程序入口 -> 测试代码.
if __name__ == '__main__':
    # 1. 手动指定配置文件路径 -> 用于测试, 实际使用可忽略.
    # config_file = 'D:/workspace/ai_30_bj/integrated_qa_system/config.ini'      # 绝对路径.
    config_file = '../config.ini'      # 相对路径.

    # 2. 实例化Config类 -> 加载并解析配置文件.
    conf = Config(config_file)
    # 3. 测试: 获取各服务配置参数.
    print(f'mysql: {conf.MYSQL_HOST}, {conf.MYSQL_USER}, {conf.MYSQL_PASSWORD}, {conf.MYSQL_DATABASE}')
    print(f'redis: {conf.REDIS_HOST}, {conf.REDIS_PORT}, {conf.REDIS_PASSWORD}, {conf.REDIS_DB}')
    print(f'log: {conf.LOG_FILE}')