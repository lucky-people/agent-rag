# 该脚本用于: 向量存储和检索.
# 该脚本用于: 向量存储和检索.
# 该脚本用于: 向量存储和检索.
# 核心流程: 文档向量生成(BGE-M3) -> 向量入库(Milvus) -> 混合检索(稠密 + 稀疏向量) -> 结果去重 -> 重排序 -> 返回精准文档.
# 常用的检索策略介绍:
#   1. 密集检索: 语义级匹配 -> '苹果关机'匹配'IPhone重启'
#   2. 稀疏检索: 关键词级过滤 -> 去合同中找'违约责任'
#   3. 多向量检索: 逐词细节对比 -> 区分'人工智能'和'AI'
# 好处: 覆盖'语义理解-快速过滤-细节对比'全场景, 适用于: 智能客服,法律文档定位,论文对比分析...

# BGE-M3模型介绍: 是一款超全能的文本'翻译器' + '搜索引擎', 能把文字转成词向量, 帮计算机快速理解和检索信息.

from Agent.legal_qa.rag_qa.utils.ssl_fix import apply_ssl_fix
apply_ssl_fix()


import numpy as np
# 模型设备相关: 判断GPU是否可用, 为模型选择运行设备.
import torch.cuda
# 导入 BGE-M3 嵌入函数，用于生成文档和查询的向量表示
from milvus_model.hybrid import BGEM3EmbeddingFunction
# 导入 Milvus 相关类，用于操作向量数据库, 例如: 客户端, 数据类型, 检索请求, 排序器
from pymilvus import MilvusClient, DataType, AnnSearchRequest, WeightedRanker
# 导入 Document 类，用于创建文档对象, 即: 统一文档数据格式(含内容 + 元数据)
from langchain_core.documents import Document
# 导入 CrossEncoder，用于重排序和 NLI 判断 -> 优化检索结果的相关性排序.
from sentence_transformers import CrossEncoder
# 导入 hashlib 模块，用于生成唯一 ID 的哈希值 -> 作为Milvus的主键.

from Agent.legal_qa.rag_qa.core.document_processor import process_documents
import hashlib
import os

# 统一使用以 Agent.legal_qa 为根的绝对导入, 不再手动修改 sys.path.
from Agent.legal_qa.base.config import Config
from Agent.legal_qa.base.logger import logger

# 定位 rag_qa 目录: 不修改 sys.path, 仅用于拼接本地模型(bert/reranker)路径.
rag_qa_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# todo 2.初始化全局配置 -> 实例化配置对象.
conf = Config()

# todo 3.定义VectorStore类: 封装向量库的核心操作 -> 集合管理, 文档入库, 混合检索, 结果处理.
class VectorStore:
    # todo 3.1 初始化方法 -> 配置向量库连接, 加载模型, 初始化客户端.
    def __init__(
        self,
        collection_name=conf.MILVUS_COLLECTION_NAME,        # Milvus集合名 -> 类似于SQL的表名, 这里我们叫: edurag_final
        host=conf.MILVUS_HOST,                              # Milvus主机地址
        port=conf.MILVUS_PORT,                              # Milvus端口
        database=conf.MILVUS_DATABASE_NAME                  # Milvus数据库名
    ):
        # 1. 存储Milvus的核心设置.
        self.collection_name = collection_name
        self.host = host
        self.port = port
        self.database = database

        # 2. 初始化日志实例.
        self.logger = logger

        # 3. (扩展)选择模型运行设备 -> 优先使用GPU, 无GPU则用CPU
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.logger.info(f'使用设备: {self.device}')

        # 4. 初始化BGE-Reranker重排序模型 -> 优化检索结果相关性排序.
        # 4.1 拼接重排序模型的本地路径. 即: rag_qa/models/bge-reranker-large
        reranker_path = os.path.join(rag_qa_path, 'models', 'bge-reranker-large')
        # print(f'reranker_path: {reranker_path}')

        # 4.2 加载模型 -> 指定运行设备,  模型用于计算'查询-文档'的相关性得分.
        self.reranker = CrossEncoder(reranker_path, device=self.device)

        # 5. 初始化BGE-M3模型 -> 用于生成文档和查询的向量表示.
        # 5.1 拼接模型文件的本地路径. 即: rag_qa/models/bge-m3
        m3_path = os.path.join(rag_qa_path, 'models', 'bge-m3')
        # 5.2 加载模型 -> 模型用于生成文档和查询的向量表示.
        self.embedding_function = BGEM3EmbeddingFunction(
            model_name_or_path=m3_path,         # 模型本地路径
            use_fp16=(self.device == 'cuda'),   # GPU时启用半精度计算(减少内存占用, 提升速度), CPU时禁用
            device=self.device)

        # 6. 获取BGE-M3稠密向量的维度: 固定输出1024维稠密向量.
        self.dense_dim = self.embedding_function.dim['dense']
        # print(f'稠密向量的维度: {self.dense_dim}')  # 结果: 1024

        # 7. 初始化Milvus客户端, 建立: Milvus向量库连接.
        # uri格式: http://主机地址:端口号, db_name 指定要连接的数据库.
        self.client = MilvusClient(uri=f"http://{self.host}:{self.port}", db_name=self.database)

        # 8. 调用'私有'方法 -> 创建新集合(若不存在) 或 加载已有集合(若存在)
        self._create_or_load_collection()


    # todo 3.2 私有方法: 创建新集合(若不存在) 或 加载已有集合(若存在)
    def _create_or_load_collection(self):
        # 1. 检查指定集合是否已存在(避免重复创建)
        if not self.client.has_collection(self.collection_name):
            # 走这里, 说明集合不存在, 需要创建集合.
            # 2. 创建集合 Schema，禁用自动 ID(手动用文档哈希作为主键)，启用动态字段
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)
            # 添加 ID 字段，作为主键，VARCHAR 类型，最大长度 100
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=100)
            # 添加文本字段，VARCHAR 类型，最大长度 65535
            schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535)
            # 添加稠密向量字段，FLOAT_VECTOR 类型，维度由嵌入函数指定
            schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=self.dense_dim)
            # 添加稀疏向量字段，SPARSE_FLOAT_VECTOR 类型
            schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
            # 添加父块 ID 字段，VARCHAR 类型，最大长度 100
            schema.add_field(field_name="parent_id", datatype=DataType.VARCHAR, max_length=100)
            # 添加父块内容字段，VARCHAR 类型，最大长度 65535
            schema.add_field(field_name="parent_content", datatype=DataType.VARCHAR, max_length=65535)
            # 添加学科类别字段，VARCHAR 类型，最大长度 50
            schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=50)
            # 添加时间戳字段，VARCHAR 类型，最大长度 50
            schema.add_field(field_name="timestamp", datatype=DataType.VARCHAR, max_length=50)

            # 3.创建索引参数对象
            index_params = self.client.prepare_index_params()
            # 为稠密向量字段添加 IVF_FLAT 索引，度量类型为内积 (IP)
            index_params.add_index(
                field_name="dense_vector",
                index_name="dense_index",
                index_type="IVF_FLAT",
                metric_type="IP",
                params={"nlist": 128}
            )
            # 为稀疏向量字段添加 SPARSE_INVERTED_INDEX 索引，度量类型为内积 (IP)
            index_params.add_index(
                field_name="sparse_vector",
                index_name="sparse_index",
                index_type="SPARSE_INVERTED_INDEX",
                metric_type="IP",
                params={"drop_ratio_build": 0.2}        # 构建索引时,丢弃20%的低权重值(减少存储,噪声, 精度影响较小)
            )

            # 4. 创建 Milvus 集合，应用定义的 Schema 和索引参数
            self.client.create_collection(collection_name=self.collection_name, schema=schema,
                                          index_params=index_params)
            # 5.记录创建集合的日志
            logger.info(f"已创建集合 {self.collection_name}")

        # 6.如果集合已存在
        else:
            # 记录加载集合的日志
            logger.info(f"已加载集合 {self.collection_name}")
        # 7. 将集合加载到内存，确保可立即查询
        self.client.load_collection(self.collection_name)


    # todo 3.3 定义函数 -> 将文档(子块) 转换为 向量并插入Milvus
    def add_documents(self, documents):
        # 1. 提取所有文档内容列表.
        texts = [doc.page_content for doc in documents]     # 格式: ['文档1内容', '文档2内容', '文档3内容']

        # 2. 使用BGE-M3模型生成文档向量.
        # 输入: 文本列表(texts)
        # 输出: 字典, 含'dense'(稠密向量) 和 'sparse'(稀疏向量)
        embeddings = self.embedding_function(texts)

        # 3. 初始化空列表.
        data = []

        # 4. 遍历每个文档, 组装插入数据(i -> 文档索引, doc是当前的Document对象)
        for i, doc in enumerate(documents):
            # 4.1 生成文档唯一的ID -> 文档哈希值
            # encode('utf-8'):  将字符串转成字节流 -> 因为MD5哈希需要字节.
            # hexdigest():      将哈希结果转为16进制字符串(32位, 适合作为ID)
            text_hash = hashlib.md5(doc.page_content.encode('utf-8')).hexdigest()
            # 4.2 处理稀疏向量: BGE-M3返回的稀疏向量是矩阵, 需要转换为Milvus支持的字典格式.
            sparse_vector = {}      # 初始化稀疏向量字典.
            # 4.2.1 获取第i个文档的稀疏向量行 getrow(i) -> 获取矩阵的第i行.
            row = embeddings['sparse'][[i]]
            # (0, 5)	0.029301747679710388  -> (列索引, 权重)     shape:  (1, 250002)
            # print(f'稀疏向量行: {row}, shape: {row.shape}')

            # 4.2.2 获取稀疏向量的非零值索引 和 对应的权重.
            indics = row.indices     # 非零值的索引列表, 例如: [10, 25, 50]
            # print(f'非零值的索引列表: {indics}')
            values = row.data        # 非    111零值的权重列表, 例如: [0.8, 0.5, 0.3]

            # 4.2.3 组装稀疏向量字典, 将索引 和 权重配对.
            for idx, value in zip(indics, values):      # {10:0.8, 25:0.5, 50:0.3...}
                sparse_vector[idx] = value
                # print(f'稀疏向量字典: {sparse_vector}, 稀疏向量字典长度: {len(sparse_vector)}')

                # --------------修改部分-----------------
            dense_vec = embeddings["dense"][i]
            # 确保是 numpy 数组，且数据类型为 float32
            if not isinstance(dense_vec, np.ndarray):
                dense_vec = np.array(dense_vec, dtype=np.float32)
            elif dense_vec.dtype != np.float32:
                dense_vec = dense_vec.astype(np.float32)
                # -------------修改结束--------------------

                # 扩展: 查看稠密向量及维度.
                # print(f'稠密向量: {embeddings["dense"][i]}, 稠密向量维度: {len(embeddings["dense"][i])}')

            # 4.3 组装单条插入数据 -> 字段要和Schema完全对应.
            data.append({
                "id": text_hash,                                        # 唯一ID(md5哈希)
                "text": doc.page_content,                               # 文档内容
               # "dense_vector": embeddings["dense"][i],                 # 稠密向量(BGE-M3生成)
                "dense_vector": dense_vec,  # 使用转换后的向量
                "sparse_vector": sparse_vector,                         # 稀疏向量(组装后的字典形式)
                "parent_id": doc.metadata["parent_id"],                 # 父文档ID(从元数据获取, 例如: doc_0_parent_0)
                "parent_content": doc.metadata["parent_content"],       # 父文档内容(从元数据获取, 用于: 上下文补充)
                "source": doc.metadata.get("source", "unknown"),        # 学科类别(从元数据获取, 例如: ai)
                "timestamp": doc.metadata.get("timestamp", "unknown")   # 时间戳(从元数据获取)
            })

        # 5. 插入数据到Milvus -> 仅当data非空时执行.
        if data:
            # 使用upsert操作: 相同ID则更新, 不存在则插入(避免重复)
            self.client.upsert(collection_name=self.collection_name, data=data)
            # 记录日志
            logger.info(f'已插入/更新 {len(data)} 条数据到集合 {self.collection_name}')


    # todo 3.4 定义函数 -> 混合检索(稠密 + 稀疏)  + 重排序, 返回精准父文档.
    def hybrid_search_with_rerank(self, query, k=conf.RETRIEVAL_K, source_filter=None):
        """
        该函数用于执行: 混合检索(稠密 + 稀疏向量) + 结果重排序, 返回精准父文档
        :param query: 用户查询文本, 例如: 'AI学科的课程内容是什么'
        :param k: 混合检索返回的TopK子块数量
        :param source_filter: 学科过滤条件, 例如: ai, 仅检索该学科的文档, 默认None不过滤.
        :return: 重排序后的Top-M个父文档列表(M是从conf中获取的)
        """
        # 1.使用 BGE-M3 嵌入函数生成查询的嵌入
        query_embeddings = self.embedding_function([query])
        # 2.获取查询的稠密向量
        dense_query_vector = query_embeddings["dense"][0]

        # ——————————————————————-修改部分——————————————————————————
        if not isinstance(dense_query_vector, np.ndarray):
            dense_query_vector = np.array(dense_query_vector, dtype=np.float32)
        elif dense_query_vector.dtype != np.float32:
            dense_query_vector = dense_query_vector.astype(np.float32)
        # ——————————————————————-修改结束——————————————————————————


        # 3.初始化查询的稀疏向量字典
        sparse_query_vector = {}
        # 3.1 获取查询稀疏向量的第 0 行数据 -> 仅1个查询, 故取第0行.
        row = query_embeddings["sparse"][[0]]
        # 3.2 获取稀疏向量的非零值索引
        indices = row.indices           # 索引列表
        # 3.3 获取稀疏向量的非零值
        values = row.data               # 权重列表
        # 3.4 将索引和值配对，填充稀疏向量字典
        for idx, value in zip(indices, values):
            sparse_query_vector[idx] = value

        # 4. 构建检索过滤表达式: 按学科过滤 -> 若source_filter存在.
        filter_expr = f"source == '{source_filter}'" if source_filter else ""
        # print(f'filter_expr: {filter_expr}')

        # 5. 构建稠密向量检索请求: 定义稠密向量的检索参数.
        dense_request = AnnSearchRequest(
            data=[dense_query_vector],      # 查询向量, 列表格式.
            anns_field='dense_vector',      # 检索的向量字段
            param={'metric_type':'IP', "params": {'nprobe': 10}},  # 内积相似度, 检索时访问的聚类数(平衡速度和精度)
            limit=k,            # 返回Tok-K结果
            expr=filter_expr    # 应用过滤表达式.
        )

        # 6. 构建稀疏向量检索请求: 构建稀疏向量的检索参数.
        sparse_request = AnnSearchRequest(
            data=[sparse_query_vector],      # 列表格式.
            anns_field='sparse_vector',      # 检索的向量字段
            param={'metric_type':'IP', "params": {}},  # 稀疏向量无需额外参数, 只需要指定内积相似度
            limit=k,            # 检索Tok-K结果
            expr=filter_expr    # 应用过滤表达式.
        )

        # 7. 创建加权排序器 -> 融合稠密和稀疏检索的结果, 按权重计算最终得分.
        # 权重逻辑: 稠密向量侧重语义相似度, 稀疏向量侧重关键词匹配, 可根据业务调整.
        ranker = WeightedRanker(1.0, 0.7)       # 稠密向量权重: 1.0, 稀疏向量权重: 0.7

        # 8. 执行混合检索 -> 获取稠密和稀疏向量的检索结果., 返回Top-K子块
        results = self.client.hybrid_search(
            collection_name=self.collection_name,       # 目标集合
            reqs=[dense_request, sparse_request],       # 混合检索请求列表(稠密向量, 稀疏向量)
            ranker=ranker,                              # 加权排序器
            limit=k,                                    # 检索Tok-K结果
            output_fields=["text", "parent_id", "parent_content", "source", "timestamp"]
        )[0]        # 因为就1个查询, 所以返回第0个元素.
        # print(f'results: {results}, 类型: {type(results)}, 数据量: {len(results)}')    # 列表类型.

        # 9. 将检索结果转换为 LangChain Document对象 -> 统一格式, 便于后续处理.
        sub_chunks = [self._doc_from_hit(hit["entity"]) for hit in results]
        # print(f'子块列表: {sub_chunks}, 数据量: {len(sub_chunks)}')      # [Document对象, Document对象, ...]

        # 10. 从子块中提取去重的父文档 -> 避免同一父块的多个子块重复返回.
        parent_docs = self._get_unique_parent_docs(sub_chunks)
        # print(f'(去重后)父文档列表: {parent_docs}, 数据量: {len(parent_docs)}')  # 数据量: 1

        # 11. 重排序逻辑: 父文档数量<2时跳过排序(无需优化) -> 直接返回.
        # if len(parent_docs) < 2:
        #     return parent_docs[:conf.CANDIDATE_M]

        # -----------------------  关键修改 -------------------------


        # 10. 从子块中提取去重的父文档
        parent_docs = self._get_unique_parent_docs(sub_chunks)

        # 11. 重排序逻辑（速度优化版）
        if len(parent_docs) == 0:
            return []
        # 候选父文档数 <= 最终需要的数量时，无需重排（重排主要是为了从更多候选中挑出 Top-M）
        if len(parent_docs) <= conf.CANDIDATE_M:
            return parent_docs[:conf.CANDIDATE_M]

        # len(parent_docs) > CANDIDATE_M 时才执行重排序，选出更相关的 Top-M
        try:
            pairs = [[query, doc.page_content] for doc in parent_docs]
            scores = self.reranker.predict(pairs)

            # 按得分降序排序
            ranked_parent_docs = [
                doc for _, doc in sorted(
                    zip(scores, parent_docs),
                    key=lambda x: x[0],  # 只按分数排序
                    reverse=True
                )
            ]
            return ranked_parent_docs[:conf.CANDIDATE_M]
        except Exception as e:
            logger.error(f"重排序失败: {e}")
            return parent_docs[:conf.CANDIDATE_M]
        # -----------------------  修改结束 -------------------------


        # # 12. 父文档数量 >= 2时, 执行重排序, 提升相关性.
        # if parent_docs:
        #     # 12.1 构建'查询-文档'配对列表, 重排序模型需要改格式输入, 每个配对为 [query, doc_content]
        #     pairs = [[query, doc.page_content] for doc in parent_docs]
        #     # 12.2 计算相关得分.
        #     scores = self.reranker.predict(pairs)
        #     # print(f'相关得分: {scores}')
        #     # 12.3 按得分降序排序 -> 将得分与父文档配对, 按得分从高到低排序.
        #     ranked_parent_docs = [doc for _, doc in sorted(zip(scores, parent_docs), reverse=True)]
        # else:
        #     # 12.4 若父文档列表为空, 返回空列表.
        #     ranked_parent_docs = []
        #
        # # 13. 返回重排序后的父文档列表 -> Top-M个父文档
        # return ranked_parent_docs[:conf.CANDIDATE_M]



    # todo 3.5 定义函数 -> 从子块列表中提取去重的父文档.
    def _get_unique_parent_docs(self, sub_chunks):
        # 初始化集合，用于存储已处理的父块内容（去重）
        parent_contents = set()
        # 初始化列表，用于存储唯一父文档
        unique_docs = []
        # 遍历所有子块
        for chunk in sub_chunks:
            # 获取子块的父块内容，默认为子块内容
            parent_content = chunk.metadata.get("parent_content", chunk.page_content)
            # 检查父块内容是否非空且未重复
            if parent_content and parent_content not in parent_contents:
                # 创建新的 Document 对象，包含父块内容和元数据
                unique_docs.append(Document(page_content=parent_content, metadata=chunk.metadata))
                # 将父块内容添加到去重集合
                parent_contents.add(parent_content)
        # 返回去重后的父文档列表
        return unique_docs



    # todo 3.6 定义函数 -> 将Milvus结果(hit) 转换为 LangChain Document对象.
    def _doc_from_hit(self, hit):
        # 创建并返回 Document 对象，填充内容和元数据
        return Document(
            page_content=hit.get("text"),
            metadata={
                "parent_id": hit.get("parent_id"),
                "parent_content": hit.get("parent_content"),
                "source": hit.get("source"),
                "timestamp": hit.get("timestamp")
            }
        )



# todo 4.测试代码.
if __name__ == '__main__':
    # 1. 实例化VectorStore对象 -> 自动连接Milvus, 创建/加载集合.
    vector_store = VectorStore()

    # 2.向量入库动作
    # 2.1 定义遍历, 记录: 文档目录.
    directory_path = '../data/民法典'
    # 密集向量dense -> 抓整体语义, 避免'关键词不同但是意思相近'的文本被漏掉.
    # COLBERT -> 抓词级上下文, 解决'同词异义'的匹配问题.
    # 稀疏向量sparse -> 抓关键词权重, 确保'特定术语'能精准命中.
    # embedding_function.dim -> {'dense': 1024, 'colbert_vecs': 1024, 'sparse': 250002}
    # print(f'embedding_function.dim -> {vector_store.embedding_function.dim}')

    # 2.2 获取所有的处理后的文档.
    documents = process_documents(directory_path)       # 79个块
    # # 2.3 添加文档到Milvus中.
    vector_store.add_documents(documents)

    # # 3.混合检索 + 结果重拍, 例如: 查询'AI学科的课程内容是什么', 过滤AI学科文档.
    # # query = 'LLM是什么'
    # query = 'AI学科的课程内容是什么'
    # query = '税务人员违反法律应该如何处理？'
    # results = vector_store.hybrid_search_with_rerank(query, source_filter='刑法')
    #
    # # 打印检索将诶过, 查看结果数量 和 具体内容.
    # print(f'results: {results}')            # 结果列表: Document对象
    # print(f'results数量: {len(results)}')    # 结果数量: 0 ~ 2区间