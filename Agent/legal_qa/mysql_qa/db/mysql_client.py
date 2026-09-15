# 该脚本用于: MySQL数据库的基础操作.

import pymysql
import pandas as pd
from Agent.legal_qa.base.config import Config
from Agent.legal_qa.base.logger import logger


class MySQLClient:
    def __init__(self):
        self.logger = logger
        try:
            self.connection = pymysql.connect(
                host=Config().MYSQL_HOST,
                user=Config().MYSQL_USER,
                password=Config().MYSQL_PASSWORD,
                database=Config().MYSQL_DATABASE
            )

            self.cursor = self.connection.cursor()
            self.logger.info("MySQL 连接成功")
        except pymysql.MySQLError as e:
            self.logger.error(f"MySQL 连接失败: {e}")
            raise

    def create_table(self):
        create_table_query = '''
        CREATE TABLE IF NOT EXISTS jpkb(
            id INT AUTO_INCREMENT PRIMARY KEY,
            subject_name VARCHAR(20),
            question VARCHAR(1000),
            answer VARCHAR(1000))
        '''
        try:
            self.cursor.execute(create_table_query)
            self.connection.commit()
            self.logger.info("表创建成功")
        except pymysql.MySQLError as e:
            self.logger.error(f"表创建失败: {e}")
            raise

    def insert_data(self, csv_path):
        try:
            data = pd.read_csv(csv_path)
            for _, row in data.iterrows():
                insert_query = "INSERT INTO jpkb (subject_name, question, answer) VALUES (%s, %s, %s)"
                self.cursor.execute(insert_query, (row['学科名称'], row['问题'], row['答案']))
            self.connection.commit()
            self.logger.info("数据插入成功")
        except Exception as e:
            self.logger.error(f"数据插入失败: {e}")
            self.connection.rollback()
            raise


    def fetch_questions(self):
        try:
            self.cursor.execute("SELECT question FROM jpkb")

            results = self.cursor.fetchall()

            self.logger.info("成功获取问题")

            return results
        except pymysql.MySQLError as e:
            self.logger.error(f"查询失败: {e}")
            return []

    def fetch_answer(self, question):
        try:
            self.cursor.execute(
                "SELECT answer FROM jpkb WHERE question LIKE %s LIMIT 1",
                (f"%{question.strip()}%",)
            )

            result = self.cursor.fetchone()

            return result[0] if result else None
        except pymysql.MySQLError as e:
            self.logger.error(f"答案获取失败: {e}")
            return None


    def close(self):
        try:
            self.connection.close()
            self.logger.info("MySQL 连接已关闭")
        except pymysql.MySQLError as e:
            self.logger.error(f"关闭连接失败: {e}")

if __name__ == '__main__':
    mysql_client = MySQLClient()
    mysql_client.create_table()
    mysql_client.insert_data('../data/law_knowledge.csv')


