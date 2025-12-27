"""读取当前图谱的所有漏洞和ref"""
import json
from py2neo import Graph

graph = Graph(
    "bolt://101.6.69.161:7688",
    auth=("neo4j", "neo4jneo4jgo")
)

query = """
MATCH (v:vuln)-[]->(r:reference)
RETURN v.id AS vuln_id, collect(r) AS refs
"""

data = graph.run(query)

vuln_ref_dict = {}

for record in data:
    vuln_id = record["vuln_id"]
    refs = record["refs"]

    # 将 Node 对象转为 dict（只取属性）
    vuln_ref_dict[vuln_id] = [dict(ref) for ref in refs]

json.dump(vuln_ref_dict, open("./cve_complement/data/cve2ref.json", "w"), indent=4)