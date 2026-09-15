# 该文件用于帮助 rag_qa这个Python包, 管理包内的脚本, 方便其它包的调用.

# 导包动作: 统一使用以 Agent.legal_qa 为根的绝对导入, 不再手动修改 sys.path.
from Agent.legal_qa.rag_qa.core.prompts import RAGPrompts         # RAG系统的提示语
from Agent.legal_qa.rag_qa.core.vector_store import VectorStore   # 向量存储和检索
from Agent.legal_qa.rag_qa.core.new_rag_system import RAGSystem   # RAG系统的核心代码 -> 添加历史记录 和 流式输出时选择.

__all__ = ["RAGPrompts", "VectorStore", "RAGSystem"]
