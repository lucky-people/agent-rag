# -*- coding: utf-8 -*-
import warnings
warnings.filterwarnings("ignore")
from pymilvus import MilvusClient

c = MilvusClient(uri="http://localhost:19530", db_name="laws_all")
colls = c.list_collections()
print("laws_all 库集合:", colls)
for col in colls:
    stats = c.get_collection_stats(col)
    print(f"{col}: row_count={stats.get('row_count')}")
