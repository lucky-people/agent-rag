# 该脚本用于: Redis缓存技术.

import redis
import json


# 统一使用以 Agent.legal_qa 为根的绝对导入, 不再手动修改 sys.path.
from Agent.legal_qa.base.config import Config
from Agent.legal_qa.base.logger import logger

class RedisClient:
    def __init__(self):
        self.logger = logger

        try:
            self.client = redis.StrictRedis(
                host=Config().REDIS_HOST,
                port=Config().REDIS_PORT,
                password=Config().REDIS_PASSWORD,
                db=Config().REDIS_DB,
                decode_responses=True
            )

        except redis.RedisError as e:
            self.logger.error(f'Redis连接异常: {e}')
            raise

        self.logger.info('Redis连接成功')

    def set_data(self, key, value):
        try:
            self.client.set(key, json.dumps(value, ensure_ascii=False))
            self.logger.info(f'Redis存储数据成功: {key}')
        except redis.RedisError as e:
            self.logger.error(f'Redis存储数据失败: {e}')

    def get_data(self, key):
        try:
            data = self.client.get(key)
            return json.loads(data) if data else None
        except redis.RedisError as e:
            self.logger.error(f'Redis获取数据失败: {e}')
            return None

    def get_answer(self, query):
        try:
            answer = self.client.get(f"answer:{query}")
            if answer:
                self.logger.info(f'从Redis中获取答案成功: {query}')
                return answer
            return None
        except redis.RedisError as e:
            self.logger.error(f'从Redis中获取答案失败: {e}')
            return None

if __name__ == '__main__':

    redCli = RedisClient()

    # print(redCli.client.keys("*"))

    # print(redCli.get_data('user:1'))

    print(redCli.get_data('user:1'))


