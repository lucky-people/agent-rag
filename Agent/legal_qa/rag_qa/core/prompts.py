# 该脚本用于: RAG提示词模板.
# 该脚本核心功能: 统一管理RAG流程中所需的各类Prompt模板.
# 作用: 通过LangChain#PromptTemplate创建 Prompt 模板，将不同场景的提示词(如: 直接检索, 子查询, 回溯问题)，并返回最终的 Prompt 模板.
#      后续只需传入具体参数(例如: 上下文, 问题)即可快速生成符合需求的提示词, 避免重复编写提示词.


# 导入 PromptTemplate 类，用于创建 Prompt 模板
from langchain_core.prompts import PromptTemplate


# todo 1.定义 RAGPrompts 类，用于管理所有 Prompt 模板
class RAGPrompts:
    # todo 1.1 定义 RAG 提示模板 -> 根据上下文生成答案, 无上下文则用自身知识, 无法回答时返回: 客服信息.
    # @staticmethod
    # def rag_prompt():
    #     # 创建并返回 PromptTemplate 对象
    #     return PromptTemplate(
    #         template="""
    #         你是一个智能助手，帮助用户回答问题。
    #         如果提供了上下文，请基于上下文回答；如果没有上下文，请直接根据你的知识回答。
    #         如果答案来源于检索到的文档，请在回答中说明。
    #
    #         上下文: {context}
    #         问题: {question}
    #
    #         如果无法回答，请回复：“信息不足，无法回答，请联系人工客服，电话：{phone}。”
    #         回答:
    #         """,
    #         #   定义输入变量
    #         input_variables=["context", "question", "phone"],
    #     )

    # 定义 RAG 提示模板
    @staticmethod
    def rag_prompt():
        # 创建并返回 PromptTemplate 对象
        return PromptTemplate(
            template="""
                你是一个智能助手，帮助用户回答问题。请参考用户的助手的对话历史和上下文回答问题。
                如果提供了上下文，请基于上下文回答；如果没有上下文，请直接根据你的知识回答。
                若答案来源于检索到的文档，请简要引用法律依据（如：《民法典》第X条），但不要整段照抄上下文中的法条原文。

                对话历史: {history}
                上下文: {context}
                问题: {question}

                请用简洁、通俗的中文回答，先给结论再给依据，全文控制在 600 字以内，避免冗余（加快响应速度）。
                如果无法回答，请回复：“信息不足，无法回答，请联系人工客服，电话：{phone}。”
                回答:
                """,
            #   定义输入变量
            input_variables=["context", "history", "question", "phone"],
        )


    # todo 1.2 定义假设问题生成的 Prompt 模板 -> 生成查询时的'假设性答案', 用于提升后续的检索精度.
    @staticmethod
    def hyde_prompt():
        #   创建并返回 PromptTemplate 对象
        return PromptTemplate(
            template="""  
            假设你是用户，想了解以下问题，请生成一个简短的假设答案：  
            问题: {query}  
            假设答案:  
            """,
            #   定义输入变量
            input_variables=["query"],
        )

    # todo 1.3 定义子查询生成的 Prompt 模板 -> 将长/复杂查询拆分为多个简单子查询, 便于分布检索.
    @staticmethod
    def subquery_prompt():
        #   创建并返回 PromptTemplate 对象
        return PromptTemplate(
            template="""  
            将以下复杂查询分解为多个简单子查询，每行一个子查询：  
            查询: {query}  
            子查询:  
            """,
            #   定义输入变量
            input_variables=["query"],
        )

    # todo 1.4 定义回溯问题生成的 Prompt 模板 -> 将复杂/冗长查询简化为简短问题, 提升检索关键词集中度.
    @staticmethod
    def backtracking_prompt():
        #   创建并返回 PromptTemplate 对象
        return PromptTemplate(
            template="""  
            将以下复杂查询简化为一个更简单的问题：  
            查询: {query}  
            简化问题:  
            """,
            #   定义输入变量
            input_variables=["query"],
        )

# todo 2. 测试代码.
if __name__ == '__main__':
    # 测试1: 基础RAG回答模版 -> 直接检索.
    # 1. 创建 RAG 提示模板类的实例
    rag_prompt = RAGPrompts.rag_prompt()
    # 2. 测试RAG基础模板.
    result = rag_prompt.format(context="黑马程序员是一家IT培训结构,主打Python,AI等课程",
                               question="这家机构的名字叫什么?",
                               phone="13112345678",
                               history=""
                               )
    # 3. 打印结果
    print(result)
    print('♥️' * 30)

    # 测试2: HyDE假设答案.
    # 1. 创建 HyDE 提示模板类的实例
    hyde_prompt = RAGPrompts.hyde_prompt()
    # 2. 测试HyDE模板.
    result = hyde_prompt.format(query="如何培养孩子的专注力")
    # 3. 打印结果
    print(result)