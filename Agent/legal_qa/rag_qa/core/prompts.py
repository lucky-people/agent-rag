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



    # todo 1.5 (Agentic RAG) 检索规划 Prompt -> 让 LLM(Agent) 自主决定检索词与检索策略
    @staticmethod
    def retrieval_plan_prompt():
        return PromptTemplate(
            template="""
你是一个检索规划器。用户的问题是：{query}

请自主决定本次 RAG 检索方案，输出严格 JSON（不要输出任何其他文字）：
{{"queries": ["检索词1", "检索词2"], "strategy": "直接检索|假设问题检索|子查询检索|回溯问题检索", "reason": "一句话说明为什么这么规划"}}

要求：
- queries：1-3 个检索词。第一个用原问题精简版；如果问题涉及多个方面（如押金+违约金），拆成多个检索词覆盖不同方面
- strategy：根据问题复杂度选择：意图明确选"直接检索"；抽象开放选"假设问题检索"；多实体多维度选"子查询检索"；冗长复杂选"回溯问题检索"
- 检索词必须是法律问答场景下的有效关键词（如"房东不退押金怎么办" → "房东不退押金"、"押金 退还 法律规定"）
""",
            input_variables=["query"],
        )

    # todo 1.6 (Agentic RAG) 反思判断 Prompt -> Self-RAG 式: 判断答案是否被检索证据充分支持
    @staticmethod
    def reflection_prompt():
        return PromptTemplate(
            template="""
你是一个严谨的 RAG 质量评审员。请判断下面的"回答"是否被"检索证据"充分支持。

问题: {query}

检索证据（知识库条文）:
{context}

回答:
{answer}

请输出严格 JSON（不要输出任何其他文字）：
{{"supported": true或false, "reason": "一句话判断依据", "missing": "答案缺失或证据不足的关键信息（没有则填空字符串）"}}

判定标准：
- supported=true：答案的核心结论能在检索证据中找到依据，且没有遗漏问题明确要求的关键信息
- supported=false：答案无证据支撑（可能幻觉）、核心结论与证据矛盾、或问题明确要求的信息在证据和答案中都缺失
- 注意：不要因为证据略少就判 false，只有核心结论悬空或明显缺关键信息时才判 false
""",
            input_variables=["query", "context", "answer"],
        )

    # todo 1.7 (Agentic RAG) 查询改写 Prompt -> 反思不通过时改写检索词, 补充缺失证据
    @staticmethod
    def rewrite_query_prompt():
        return PromptTemplate(
            template="""
你是一个检索查询改写器。上一轮检索生成的答案证据不足，请改写检索查询，以检索到缺失的信息。

原问题: {query}
上一轮检索词: {last_queries}
缺失信息: {missing}
评审意见: {reason}

请输出严格 JSON（不要输出任何其他文字）：
{{"queries": ["改写后的检索词1", "改写后的检索词2"]}}

要求：
- 针对"缺失信息"重新构造 1-2 个更精准的检索词，重点覆盖缺失的法律要点
- 检索词应是法律条文检索友好的关键词组合（法律术语 + 场景词）
""",
            input_variables=["query", "last_queries", "missing", "reason"],
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