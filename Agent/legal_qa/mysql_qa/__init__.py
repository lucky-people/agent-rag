# 该文件用于帮助 mysql_qa这个Python包, 管理包内的脚本, 方便其它包的调用.

# 导包动作: 统一使用以 Agent.legal_qa 为根的绝对导入, 不再手动修改 sys.path.
from Agent.legal_qa.mysql_qa.db.mysql_client import MySQLClient         # MySQL的客户端
from Agent.legal_qa.mysql_qa.cache.redis_client import RedisClient      # Redis的客户端
from Agent.legal_qa.mysql_qa.retrieval.bm25_search import BM25Search    # BM25 -> 相似度检索

__all__ = ["MySQLClient", "RedisClient", "BM25Search"]
