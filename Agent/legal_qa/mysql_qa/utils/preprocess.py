# 该脚本用于: 文本预处理.
import jieba
from Agent.legal_qa.base.logger import logger

def preprocess_text(text):
    logger.info("开始处理文本")
    try:
        return jieba.lcut(text.lower())
    except AttributeError as e:
        logger.error(f"文本预处理失败: {e}")
        return []


if __name__ == '__main__':
    print(preprocess_text("学AI，月薪过万，就来黑马程序员"))