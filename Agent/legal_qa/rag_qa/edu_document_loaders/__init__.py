import sys

# 导入配置 (统一以 Agent.legal_qa 为根的绝对导入)
from Agent.legal_qa.base.config import Config

# 添加配置中指定的文档加载依赖目录到 sys.path
# (该目录内是第三方 OCR/解析工具, 不属于项目包, 因此保留该路径追加)
sys.path.append(Config().EDU_DOCUMENT_LOADERS_DIR)

# 条件导入各个文档加载器，允许在缺少依赖时继续运行
try:
    from .edu_docloader import *
except ImportError:
    pass

try:
    from .edu_pptloader import *
except ImportError:
    pass

try:
    from .edu_imgloader import *
except ImportError:
    pass

try:
    from .edu_pdfloader import *
except ImportError:
    pass
