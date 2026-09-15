#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
房租法律专项入库脚本
- 解析《商品房屋租赁管理办法》《住房租赁条例》PDF，按条文分割
- 解析《租赁合同纠纷29个裁判规则》txt，按案例分割
- 提取结构化元数据（法律名/篇章节/条号/案例类别）
- 用 BGE-M3 生成向量，存入 Milvus 集合 edurag_final
"""
import os
import sys
import re
import hashlib

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEGAL_QA_DIR = os.path.join(BASE_DIR, 'legal_qa')
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)  # 保证 Agent.legal_qa.* 绝对导入可用

from Agent.legal_qa.rag_qa.core.vector_store import VectorStore
from langchain_core.documents import Document

# 新法律数据目录
DATA_DIR = r"D:\heima_lesson\多智能体+RAG综合项目\RAG\法律条文\房租法"


def extract_pdf_text(pdf_path):
    """提取 PDF 全文，优先用 fitz，备选 pypdf/pdfplumber"""
    full_text = ""
    # 方案1: PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(pdf_path)
        for page in doc:
            full_text += page.get_text() + "\n"
        doc.close()
        if full_text.strip():
            return full_text
    except ImportError:
        pass
    except Exception as e:
        print(f"  fitz 提取失败: {e}")

    # 方案2: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
        if full_text.strip():
            return full_text
    except ImportError:
        pass
    except Exception as e:
        print(f"  pypdf 提取失败: {e}")

    # 方案3: pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                full_text += page.extract_text() + "\n"
        if full_text.strip():
            return full_text
    except ImportError:
        pass
    except Exception as e:
        print(f"  pdfplumber 提取失败: {e}")

    if not full_text.strip():
        print("  警告: 所有 PDF 提取方案均失败，请安装 PyMuPDF: pip install PyMuPDF")
    return full_text


def split_law_articles(text, law_name):
    """
    将法律文本按"第X条"分割，提取结构化元数据。
    返回 list[Document]
    """
    docs = []
    # 匹配"第X条"开头（支持中文数字和阿拉伯数字）
    pattern = re.compile(r'(第[一二三四五六七八九十百千零\d]+条\s*)')
    parts = pattern.split(text)

    # parts[0] 是条文之前的内容（总则等），parts[1]是条号, parts[2]是条文内容...
    current_chapter = ""
    current_section = ""

    # 先从前言部分提取章/节
    preamble = parts[0] if parts else ""
    # 匹配"第X章"和"第X节"
    chapter_match = re.findall(r'第[一二三四五六七八九十百千]+章\s*([^\n]*)', preamble)
    if chapter_match:
        current_chapter = chapter_match[-1].strip()

    i = 1
    while i < len(parts):
        article_num = parts[i].strip()
        article_content = parts[i + 1] if i + 1 < len(parts) else ""
        i += 2

        # 从条文中提取章/节（如果条文中包含章标题）
        chapter_in_article = re.search(r'第[一二三四五六七八九十百千]+章\s*([^\n]*)', article_content)
        if chapter_in_article:
            current_chapter = chapter_in_article.group(1).strip()
            # 移除章标题行
            article_content = re.sub(r'第[一二三四五六七八九十百千]+章\s*[^\n]*\n', '', article_content)

        full_content = f"{article_num} {article_content}".strip()
        if len(full_content) < 10:
            continue

        # 结构化元数据
        parent_id = f"{law_name}_{article_num}"
        metadata = {
            "source": law_name,
            "law_name": law_name,
            "chapter": current_chapter,
            "section": current_section,
            "article": article_num,
            "doc_type": "法律条文",
            "category": "房屋租赁",
            "parent_id": parent_id,
            "parent_content": full_content,
            "timestamp": "2026-08-24",
        }

        docs.append(Document(page_content=full_content, metadata=metadata))

    return docs


def parse_judgment_rules(txt_path):
    """
    解析裁判规则 txt，按案例分割。
    返回 list[Document]
    """
    with open(txt_path, 'r', encoding='utf-8') as f:
        text = f.read()

    docs = []
    current_category = ""

    # 匹配类别标题："一、xxx" "二、xxx" 等
    # 匹配案例："数字.案例名称【案号】"
    lines = text.split('\n')
    current_case = ""
    current_content = []
    case_num = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 检测类别标题
        cat_match = re.match(r'^[一二三四五六七八九十]+、(.+)', line)
        if cat_match:
            # 保存上一个案例
            if current_case and current_content:
                case_num += 1
                full_content = f"{current_case}\n" + "\n".join(current_content)
                parent_id = f"裁判规则_{case_num}"
                metadata = {
                    "source": "租赁合同纠纷裁判规则",
                    "law_name": "裁判规则",
                    "case_category": current_category,
                    "case_name": current_case,
                    "case_number": str(case_num),
                    "doc_type": "裁判案例",
                    "category": "房屋租赁",
                    "parent_id": parent_id,
                    "parent_content": full_content,
                    "timestamp": "2026-08-24",
                }
                docs.append(Document(page_content=full_content, metadata=metadata))
            current_category = cat_match.group(1).strip()
            current_case = ""
            current_content = []
            continue

        # 检测案例开头："数字.案例名称【案号】"
        case_match = re.match(r'^(\d+)\.(.+?)(?:【|$)', line)
        if case_match:
            # 保存上一个案例
            if current_case and current_content:
                case_num += 1
                full_content = f"{current_case}\n" + "\n".join(current_content)
                parent_id = f"裁判规则_{case_num}"
                metadata = {
                    "source": "租赁合同纠纷裁判规则",
                    "law_name": "裁判规则",
                    "case_category": current_category,
                    "case_name": current_case,
                    "case_number": str(case_num),
                    "doc_type": "裁判案例",
                    "category": "房屋租赁",
                    "parent_id": parent_id,
                    "parent_content": full_content,
                    "timestamp": "2026-08-24",
                }
                docs.append(Document(page_content=full_content, metadata=metadata))
            current_case = line
            current_content = []
            continue

        # 案例内容
        if current_case:
            current_content.append(line)

    # 保存最后一个案例
    if current_case and current_content:
        case_num += 1
        full_content = f"{current_case}\n" + "\n".join(current_content)
        parent_id = f"裁判规则_{case_num}"
        metadata = {
            "source": "租赁合同纠纷裁判规则",
            "law_name": "裁判规则",
            "case_category": current_category,
            "case_name": current_case,
            "case_number": str(case_num),
            "doc_type": "裁判案例",
            "category": "房屋租赁",
            "parent_id": parent_id,
            "parent_content": full_content,
            "timestamp": "2026-08-24",
        }
        docs.append(Document(page_content=full_content, metadata=metadata))

    return docs


def main():
    print("=" * 60)
    print("房租法律专项入库开始")
    print("=" * 60)

    # 初始化向量库（会自动加载 BGE-M3 模型，首次较慢）
    print("\n[1/4] 初始化向量库（加载 BGE-M3 模型）...")
    vs = VectorStore()
    print(f"  集合: {vs.collection_name}")
    print(f"  设备: {vs.device}")

    all_docs = []

    # 2. 解析《商品房屋租赁管理办法》PDF
    print("\n[2/4] 解析《商品房屋租赁管理办法》...")
    pdf1 = os.path.join(DATA_DIR, "商品房屋租赁管理办法_住房和城乡建设部_中国政府网.pdf")
    if os.path.exists(pdf1):
        text1 = extract_pdf_text(pdf1)
        docs1 = split_law_articles(text1, "商品房屋租赁管理办法")
        print(f"  提取到 {len(docs1)} 条法律条文")
        all_docs.extend(docs1)
    else:
        print(f"  文件不存在: {pdf1}")

    # 3. 解析《住房租赁条例》PDF
    print("\n[3/4] 解析《住房租赁条例》...")
    pdf2_candidates = [f for f in os.listdir(DATA_DIR) if f.endswith('.pdf') and '住房租赁' in f]
    if pdf2_candidates:
        pdf2 = os.path.join(DATA_DIR, pdf2_candidates[0])
        text2 = extract_pdf_text(pdf2)
        docs2 = split_law_articles(text2, "住房租赁条例")
        print(f"  提取到 {len(docs2)} 条法律条文")
        all_docs.extend(docs2)
    else:
        print("  未找到住房租赁条例 PDF")

    # 4. 解析裁判规则 txt
    print("\n[4/4] 解析《租赁合同纠纷29个裁判规则》...")
    txt_file = os.path.join(DATA_DIR, "租赁合同纠纷29个裁判规则.txt")
    if os.path.exists(txt_file):
        docs3 = parse_judgment_rules(txt_file)
        print(f"  提取到 {len(docs3)} 个裁判案例")
        all_docs.extend(docs3)
    else:
        print(f"  文件不存在: {txt_file}")

    print(f"\n总计: {len(all_docs)} 个文档待入库")

    if not all_docs:
        print("没有可入库的文档，退出。")
        return

    # 去重（基于内容哈希）
    seen = set()
    unique_docs = []
    for doc in all_docs:
        h = hashlib.md5(doc.page_content.encode('utf-8')).hexdigest()
        if h not in seen:
            seen.add(h)
            unique_docs.append(doc)
    print(f"去重后: {len(unique_docs)} 个文档")

    # 入库
    print("\n开始向 Milvus 写入向量（可能需要1-3分钟）...")
    vs.add_documents(unique_docs)
    print(f"\n入库完成！共写入 {len(unique_docs)} 个文档")

    # 验证
    print("\n" + "=" * 60)
    print("验证：测试检索")
    print("=" * 60)
    test_query = "房东卖房后租客能拒绝搬走吗"
    results = vs.hybrid_search_with_rerank(test_query, k=3)
    print(f"\n查询: {test_query}")
    print(f"检索到 {len(results)} 条结果:")
    for i, doc in enumerate(results, 1):
        src = doc.metadata.get('source', '未知')
        art = doc.metadata.get('article', '')
        ctype = doc.metadata.get('doc_type', '')
        print(f"  [{i}] {ctype} | {src} {art}")
        print(f"      {doc.page_content[:80]}...")


if __name__ == '__main__':
    main()
