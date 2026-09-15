# 该脚本用于: 查询分类器.
# 该脚本用于: 查询分类器.
# 该脚本用于: 基于BERT模型实现查询分类器, 将用户查询分为'通用知识'和'专业咨询'两大类.
# 核心流程: 加载预训练BERT模型 -> 数据预处理 -> 模型训练 -> 模型评估 -> 预测查询类别
# 应用场景: 在RAG系统中, 可根据分类结果决定是否需要检索专业文档(例如: 专业咨询可检索文档, 通用知识由模型直接回复即可)


from Agent.legal_qa.rag_qa.utils.ssl_fix import apply_ssl_fix
apply_ssl_fix()

import warnings
warnings.filterwarnings("ignore")


# todo 1.导包
# 导入标准库
import json
import os

# 统一使用以 Agent.legal_qa 为根的绝对导入, 不再手动修改 sys.path.
# 定位 rag_qa 目录: 不修改 sys.path, 仅用于拼接本地 BERT 模型/训练产物路径.
rag_qa_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 兼容旧代码"项目根"语义(即 legal_qa 目录), 仅供底部训练 demo 使用.
project_root = os.path.dirname(rag_qa_path)

# 导入 PyTorch
import torch
# 导入日志
from Agent.legal_qa.base.logger import logger
# 导入numpy
import numpy as np
# 导入 Transformers 库
from transformers import BertTokenizer, BertForSequenceClassification       # BERT分词器和序列分类模型.
# Trainer: 负责实际执行训练过程(用模型, 数据和 TrainingArguments的配置跑训练) -> 相当于 训练任务的执行者, 按照 TrainingArguments(说明书)具体干活
# TrainingArguments: 负责定义训练的各种参数和配置(例如: 训练多久, 多大批次, 保存到哪等...) -> 相当于 训练任务的说明书,提前写好训练的各种规则和细节.
from transformers import Trainer, TrainingArguments
# 导入train_test_split
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix

# todo 2.定义QueryClassifier类: 封装BERT查询分类的完整流程 -> 模型加载, 训练, 评估, 预测...
class QueryClassifier:
    # todo 2.1 初始化方法: 配置模型路径, 加载分词器, 选择设备, 定义标签映射.
    def __init__(self, model_path='../models/bert_query_classifier'):
        # 1. 存储模型路径: 用于后续加载或保存模型.
        self.model_path = model_path
        # 2. 加载BERT分词器: 将文本转换成模型可以理解的输入.
        # 2.1 拼接预训练BERT模型的本地路径.
        bert_path = os.path.join(rag_qa_path, 'models', 'bert-base-chinese')
        # 2.2 加载分词器.
        self.tokenizer = BertTokenizer.from_pretrained(bert_path)

        # 3. 初始化模型变量, 后续通过 load_model()加载或创建模型.
        self.model = None

        # 4. 选择模型运行设备.
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        # 5. 记录日志.
        logger.info(f'使用设备: {self.device}')

        # 6. 定义标签映射: 将标签映射为模型输出的索引. 即: 通用知识 -> 0, 专业咨询 -> 1.
        self.label_map = {"通用知识": 0, "专业咨询": 1}

        # 7. 加载模型: 初始化时, 自动调用load_model(), 确保模型可用.
        self.load_model()


    # todo 2.2 加载模型方法 -> 从指定路径加载已训练模型, 若不存在则初始化新模型.
    def load_model(self):
        """
        函数功能: 加载模型, 优先从self.model_path加载, 不存在则初始化基于 bert-base-chinese的新模型
        :return:
        """
        # 1. 检查模型路径是否存在 -> 即: 是否有已训练的模型.
        if os.path.exists(self.model_path):
            # 加载预训练模型
            self.model = BertForSequenceClassification.from_pretrained(self.model_path)
            # 将模型移到指定设备
            self.model.to(self.device)
            # 记录加载成功的日志
            logger.info(f"加载模型: {self.model_path}")
        else:
            # 2. 若模型不存在, 初始化新模型
            # 参1: 模型路径（用绝对路径，避免相对路径依赖工作目录）,  参2: 二分类任务.
            bert_pretrained_path = os.path.join(rag_qa_path, 'models', 'bert-base-chinese')
            self.model = BertForSequenceClassification.from_pretrained(bert_pretrained_path, num_labels=2)
            # 将模型移到指定设备
            self.model.to(self.device)
            # 记录初始化模型的日志
            logger.info("初始化新 BERT 模型")


    # todo 2.3 保存模型的方法 -> 将训练好的模型和分词器存储到本地.
    def save_model(self):
        self.model.save_pretrained(self.model_path)
        self.tokenizer.save_pretrained(self.model_path)
        logger.info(f"保存模型至: {self.model_path}")


    # todo 2.4 数据预处理方法 -> 将文本和标签转换为BERT模型所需的输入格式.
    def preprocess_data(self, texts, labels):
        """
        函数功能: 对文本进行分词, 阶段, 填充, 将标签转换为: 数字.
        :param texts: 待处理的文本列表.
        :param labels: 文本对应的标签列表.
        :return: 处理后的编码 (input_ids, attention_mask) 和 数字标签列表.
        """
        # 1. 文本编码: 使用BERT分词器将文本转换为模型输入格式.
        encodings = self.tokenizer(
            texts,
            truncation=True,        # 超过最大长度时截断
            padding=True,           # 不足最大长度时填充.
            max_length=128,         # 最大长度
            return_tensors="pt"     # 返回张量
        )
        # 2. 标签转换: 将文本标签转换为数字
        return encodings, [self.label_map[label] for label in labels]


    # todo 2.5 创建数据集方法: 自定义Dataset类, 封装: 编码 和 标签.
    def create_dataset(self, encodings, labels):
        # 1. 定义内部Dataset类, 继承子torch.utils.data.Dataset
        class Dataset(torch.utils.data.Dataset):
            # 2. 初始化方法: 接收编码和标签, 创建内部Dataset类.
            def __init__(self, encodings, labels):
                super().__init__()
                self.encodings = encodings  # 文本编码, 格式: (input_ids, attention_mask)
                self.labels = labels        # 数字标签列表, 格式: [0, 1, 0, 1, ...]

            # 3. 根据索引返回单条数据( 编码 + 标签)
            def __getitem__(self, idx):
                item = {key: val[idx] for key, val in self.encodings.items()}
                item["labels"] = torch.tensor(self.labels[idx])
                return item

            # 4. 返回数据集长度.
            def __len__(self):
                return len(self.labels)

        # 5. 返回实例化的Dataset对象.
        return Dataset(encodings, labels)


    # todo 2.6 训练模型方法 -> 加载数据集, 预处理, 配置训练参数并训练模型.
    def train_model(self, data_file="意图识别.json"):
        """
        函数功能: 训练BERT分类模型, 区分查询分类为'通用知识' 和 '专业咨询'
        :param data_file: 数据集文件路径.
        :return: 无
        """
        # 1. 检查数据集文件是否存在.
        if not os.path.exists(data_file):
            logger.error(f"数据集文件 {data_file} 不存在")
            raise FileNotFoundError(f"数据集文件 {data_file} 不存在")

        # 2. 加载数据集, 从Json文件中读取查询文本和对应标签.
        with open(data_file, "r", encoding="utf-8") as f:
            data = [json.loads(value) for value in f.readlines()]

        # 3. 提取文本和标签, 分离查询文本和对应的分类标签.
        texts = [item["query"] for item in data]        # 格式: [查询文本1, 查询文本2, 查询文本3, ...]
        labels = [item["label"] for item in data]       # 格式: [标签1, 标签2, 标签3, ...]

        # 4. 划分训练集和测试集. 80%用于训练, 20%用于验证. 固定随机种子确保结果可复现.
        train_texts, val_texts, train_labels, val_labels = train_test_split(
            texts, labels, test_size=0.2, random_state=42
        )

        # 5. 数据预处理: 将文本和标签转换为BERT模型所需的输入格式 -> 调用自定义的preprocess_data() 预处理数据的方法.
        train_encodings, train_labels = self.preprocess_data(train_texts, train_labels)
        val_encodings, val_labels = self.preprocess_data(val_texts, val_labels)

        # 6. 创建数据集对象, 将编码 和 标签封装为PyTorch可识别的 Dataset对象.
        train_dataset = self.create_dataset(train_encodings, train_labels)
        val_dataset = self.create_dataset(val_encodings, val_labels)


        # 7. 配置训练参数: 定义模型训练的超参数.
        training_args = TrainingArguments(
            # 设置模型和检查点保存的目录路径
            output_dir=os.path.join(rag_qa_path, "models", "bert_results"),
            # 设置训练的总轮数为4轮（数据量800条，4轮可充分学习）
            num_train_epochs=4,
            # 设置每个设备（GPU/CPU）上的训练批次大小为16
            per_device_train_batch_size=16,
            # 设置每个设备（GPU/CPU）上的评估批次大小为16
            per_device_eval_batch_size=16,
            # 设置学习率为2e-5（BERT微调推荐值，比默认5e-5更稳定）
            learning_rate=2e-5,
            # 设置学习率预热步数为50步（数据量增大，预热步数相应增加）
            warmup_steps=50,
            # 设置权重衰减系数为0.01，用于防止过拟合
            weight_decay=0.01,
            # 设置日志文件保存的目录路径
            logging_dir=os.path.join(rag_qa_path, "models", "bert_logs"),
            # 设置每10个训练步骤记录一次日志
            logging_steps=10,
            # 设置评估策略为每个epoch结束后进行评估
            eval_strategy="epoch",
            # 设置模型保存策略为每个epoch结束后保存
            save_strategy="epoch",
            # 设置训练结束后加载最佳模型而非最后一个模型
            load_best_model_at_end=True,
            # 设置最多保存1个检查点文件，超出时自动删除旧的
            save_total_limit=1,
            # 设置用于判断最佳模型的指标为评估损失
            metric_for_best_model="eval_loss",
            # 禁用FP16混合精度训练，使用FP32精度 简化配置, 需要GPU支持
            fp16=False,
        )

        # 8. 初始化 Trainer: 封装模型, 训练参数, 数据集, 评估指标计算方法.
        trainer = Trainer(
            # 传入要训练的模型实例
            model=self.model,
            # 传入上面定义的训练参数配置
            args=training_args,
            # 传入训练数据集
            train_dataset=train_dataset,
            # 传入验证数据集，用于训练过程中评估模型性能
            eval_dataset=val_dataset,
            # 传入计算评估指标的函数，用于在验证集上计算准确率等指标
            compute_metrics=self.compute_metrics        # 自定义评估指标(准确率)
        )
        # 9. 训练模型
        logger.info("开始训练 BERT 模型...")
        trainer.train()
        self.save_model()

        # 10. 评估模型
        self.evaluate_model(val_texts, val_labels)


    # todo 2.7 计算评估指标方法 -> 计算模型在验证集上的准确率.
    def compute_metrics(self, eval_pred):
        """
        函数功能: 计算分类任务的评估指标(准确率)
        :param eval_pred:  包含模型输出logits 和 真实标签的元素.
        :return: 准确率字典.
        """
        # 1. 模型输出的 logits 和 真实标签.
        logits, labels = eval_pred
        # 2. 取logits最大值对应的索引作为预测结果.
        predictions = np.argmax(logits, axis=-1)
        # 3. 计算准确率: 预测正确的样本占比
        accuracy = (predictions == labels).mean()
        # 4. 返回准确率字典.
        return {"accuracy": accuracy}


    # todo 2.8 评估模型方法: 生成分类报告和混淆矩阵, 全面分析模型性能.
    def evaluate_model(self, texts, labels):
        """
        函数功能: 在给定文本和标签上评估模型, 输出分类报告和混淆矩阵.
        :param texts:  待评估的文本列表
        :param labels: 文本对应的真实标签(数字形式)
        """
        # 1. 对文本进行编码, 仅处理文本, 因为标签已经转换为数字了.
        encodings = self.tokenizer(
            texts,
            truncation=True,
            padding=True,
            max_length=128,
            return_tensors="pt"
        )

        # 2. 创建评估数据集.
        dataset = self.create_dataset(encodings, labels)

        # 3. 使用Trainer进行预测.
        trainer = Trainer(model=self.model)
        predictions = trainer.predict(dataset)

        # 4. 解析预测结果: 取logits最大值对应的索引作为预测结果.
        pred_labels = np.argmax(predictions.predictions, axis=-1)
        true_labels = labels  # 直接使用数字标签

        # 5. 记录评估结果到日志.
        logger.info("分类报告:")
        logger.info(classification_report(
            true_labels,
            pred_labels,
            target_names=["通用知识", "专业咨询"]   # 指定标签名称, 使报告更易读.
        ))

        # 混淆矩阵: 展示预测标签 和 真实标签的匹配情况.
        logger.info("混淆矩阵:")
        logger.info(confusion_matrix(true_labels, pred_labels))


    # todo 2.9 预测类别方法 -> 对单个查询文本进行分类预测.
    def predict_category(self, query):
        """
        函数功能: 对单个查询文本进行类别预测 -> 通用知识 或者 专业咨询.
        :param query: 待分类的查询文本
        :return: 类别名称(文本标签)
        """
        # 0. 规则前置兜底：租房常识/权益/押金/退租等关键词，强制走 RAG 检索，
        #    确保回答能引用具体法律条文（避免被分类器误判为通用知识而丢失引用）。
        _rental_tip_keywords = ['注意事项', '租客权益', '权益', '押金', '退租', '租房前',
                                '租房知识', '租房注意事项', '提前退租', '不退押金', '怎么退押金']
        if any(_kw in query for _kw in _rental_tip_keywords):
            logger.info(f"命中租房常识关键词，强制走专业咨询（RAG 检索）: '{query}'")
            return '专业咨询'
        # 1. 检查模型是否加载.
        if self.model is None:
            # 模型未加载
            logger.error("模型未训练或加载!")
            return '通用知识'

        # 2. 对查询文本进行编码.
        encoding = self.tokenizer(
            query,
            truncation=True,
            padding=True,
            max_length=128,
            return_tensors="pt"
        )

        # 3. 将编码数据迁移到指定设备.
        encoding = {k: v.to(self.device) for k, v in encoding.items()}

        # 4. 模型推理 -> 不计算梯度, 提高效率.
        with torch.no_grad():
            # 4.1 获取模型输出 -> 包含logits
            outputs = self.model(**encoding)
            # 4.2 获取预测结果 -> 获取logits最大值对应的索引作为预测结果.
            prediction = torch.argmax(outputs.logits, dim=1).item()

        # 5. 返回预测结果标签
        return '专业咨询' if prediction == 1 else '通用知识'





# todo 3. 测试代码.
if __name__ == '__main__':
    # 注意：上方的 project_root 实际指向 legal_qa 目录，需再往上两级才是真正的项目根目录
    # current_dir = rag_qa/core -> rag_qa_path = rag_qa -> project_root = legal_qa
    # 真正项目根目录 = os.path.dirname(os.path.dirname(project_root)) = 多智能体+RAG综合项目
    REAL_PROJECT_ROOT = os.path.dirname(os.path.dirname(project_root))

    # 1. 实例化查询分类器 -> 自动加载模型, 若无则初始化新模型.
    query_classify = QueryClassifier()

    # 2. 训练模型（使用项目内的训练数据）
    data_file = os.path.join(REAL_PROJECT_ROOT, '实验脚本', 'data', 'intent_train_data.jsonl')
    query_classify.train_model(data_file)

    # 3. 示例预测: 对查询进行分类
    test_queries = [
        '租房一般多少钱一个月',
        '房东不退押金怎么办',
        '你好',
        '合租好还是整租好',
        '租客提前退租需要承担什么责任',
    ]
    for q in test_queries:
        result = query_classify.predict_category(q)
        print(f'{q} -> {result}')