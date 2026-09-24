# -*- coding: utf-8 -*-
"""
本地模型一键下载 (HuggingFace)
==============================
法律问答链路依赖 3 个开源模型, 体积大且不入库(见 .gitignore 的 models/ 规则);
全新 clone 的环境用本脚本一次拉齐, 避免首次提问时才发现缺模型。

用法:
  python scripts/download_models.py                     # 下载全部(约 3~4GB)
  python scripts/download_models.py --only bge-m3       # 只下载指定模型(可重复指定)
  python scripts/download_models.py --list              # 查看可下载模型与用途
  python scripts/download_models.py --force             # 已存在也重新下载
  python scripts/download_models.py --dir D:/models     # 自定义目录(配合 RAG_MODEL_ROOT 使用)

国内网络可用镜像加速:
  Windows:  set HF_ENDPOINT=https://hf-mirror.com && python scripts/download_models.py
  Linux:    HF_ENDPOINT=https://hf-mirror.com python scripts/download_models.py

下载目录: Agent/legal_qa/rag_qa/models/<模型名>/
模型加载顺序(见 query_classifier.py / vector_store.py):
  1) $RAG_MODEL_ROOT/models/<模型名>
  2) Agent/legal_qa/rag_qa/models/<模型名>
  3) HuggingFace 自动下载兜底

注: 微调模型 bert_query_classifier 由本地训练产出, 不由本脚本下载:
    python scripts/train_intent_classifier.py
"""
import os
import sys
import argparse

# 统一使用以项目根为起点的路径, 避免依赖当前工作目录.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

DEFAULT_MODELS_DIR = os.path.join(PROJECT_ROOT, 'Agent', 'legal_qa', 'rag_qa', 'models')

# 模型清单: 名称 -> (HuggingFace 仓库, 用途说明, 体积量级)
MODELS = {
    'bert-base-chinese': (
        'bert-base-chinese',
        '查询分类器分词器/基础权重 + 微调训练起点',
        '约 400MB',
    ),
    'bge-m3': (
        'BAAI/bge-m3',
        '稠密 + 稀疏向量表征(混合检索的向量引擎)',
        '约 2.2GB',
    ),
    'bge-reranker-large': (
        'BAAI/bge-reranker-large',
        'CrossEncoder 精排模型(检索结果重排序)',
        '约 1.3GB',
    ),
}

# 判定"已下载完成"的标记文件: 模型目录里存在 config.json 即认为可用.
DONE_MARKER = 'config.json'


def is_downloaded(name, models_dir):
    """模型目录内存在 config.json 即视为已下载完成."""
    return os.path.exists(os.path.join(models_dir, name, DONE_MARKER))


def download_one(name, models_dir, force=False):
    """
    函数功能: 下载单个模型到 models_dir/<name>/.
    :return: True 表示成功(含已存在跳过), False 表示失败.
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        print(f'[错误] 缺少 huggingface_hub({e}), 请先执行: pip install -r requirements.txt')
        return False

    repo_id, desc, size = MODELS[name]
    target = os.path.join(models_dir, name)

    if is_downloaded(name, models_dir) and not force:
        print(f'[跳过] {name:20s} 已存在  {target}')
        return True

    os.makedirs(target, exist_ok=True)
    print(f'[下载] {name:20s} <- {repo_id}  ({desc}, {size})')
    try:
        snapshot_download(repo_id=repo_id, local_dir=target)
    except Exception as e:      # 网络/鉴权/磁盘异常统一兜底, 不中断后续模型
        print(f'[失败] {name:20s} {type(e).__name__}: {e}')
        print('       可尝试镜像: set HF_ENDPOINT=https://hf-mirror.com (Linux 用 export)')
        return False

    print(f'[完成] {name:20s} -> {target}')
    return True


def main():
    parser = argparse.ArgumentParser(description='下载法律问答链路所需的本地模型')
    parser.add_argument('--only', action='append', choices=sorted(MODELS),
                        help='只下载指定模型(可重复指定), 默认全部')
    parser.add_argument('--dir', default=DEFAULT_MODELS_DIR,
                        help=f'下载目标目录, 默认 {DEFAULT_MODELS_DIR}')
    parser.add_argument('--force', action='store_true', help='已存在也重新下载')
    parser.add_argument('--list', action='store_true', help='列出可下载模型后退出')
    args = parser.parse_args()

    if args.list:
        print('可下载模型:')
        for name, (repo_id, desc, size) in MODELS.items():
            print(f'  {name:20s} {repo_id:28s} {size:9s} {desc}')
        print('\n微调模型 bert_query_classifier 不在此列, 由本地训练产生:')
        print('  python scripts/train_intent_classifier.py')
        return 0

    names = args.only or list(MODELS)
    models_dir = os.path.abspath(args.dir)
    print(f'目标目录: {models_dir}')
    print(f'待处理: {" ".join(names)}\n')

    ok_names, bad_names = [], []
    for name in names:
        if download_one(name, models_dir, force=args.force):
            ok_names.append(name)
        else:
            bad_names.append(name)

    print('\n' + '-' * 62)
    print(f'成功 {len(ok_names)}/{len(names)}: {" ".join(ok_names) if ok_names else "-"}')
    if bad_names:
        print(f'失败 {len(bad_names)}: {" ".join(bad_names)}')
        return 1

    if os.path.abspath(models_dir) != os.path.abspath(DEFAULT_MODELS_DIR):
        print(f'提示: 模型未放在默认目录, 请设置环境变量 RAG_MODEL_ROOT={os.path.dirname(models_dir)} 后再启动')
    else:
        print('提示: 模型已就位, 可直接启动; 训练微调分类器: python scripts/train_intent_classifier.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
