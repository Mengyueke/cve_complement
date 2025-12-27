import os
import json
from urllib.parse import urlparse
from collections import defaultdict
from tqdm import tqdm
import random
random.seed(42)

MIN_PAGES =1

def get_domain(url: str) -> str:
    parsed = urlparse(url) 
    return parsed.netloc

# 基础统计数据
def check_base_statistic(data_path,out_dir,start_year=2010,end_year=2025):
    data = json.load(open(data_path, "r"))
    refs = [{"cve":cve,**item} for cve,sublist in data.items() if start_year <= int(cve.split('-')[1]) <= end_year  for item in sublist]
    
    domains_cnt = defaultdict(dict)
    for ref in tqdm(refs):
        domain = get_domain(ref["url"])
        if domain not in domains_cnt:
            domains_cnt[domain] = {"count": 0,"samples": []}
        domains_cnt[domain]["count"] += 1
        domains_cnt[domain]["samples"].append(ref)
    for domain in domains_cnt:
        domains_cnt[domain]["samples"] = random.sample(domains_cnt[domain]["samples"], min(20,len(domains_cnt[domain]["samples"])))
    sorted_domains = {k:v for k,v in sorted(domains_cnt.items(), key=lambda x: x[1]["count"], reverse=True) if v["count"]>MIN_PAGES}
    json.dump(sorted_domains, open(os.path.join(out_dir,"domains.json"), "w"), indent=4)
    tags_cnt = defaultdict(dict)
    for ref in tqdm(refs):
        tags = ref.get("tags", [])
        if not isinstance(tags, list):
            tags = tags.split(";")
        for tag in tags:
            if not tag:
                continue
            if tag not in tags_cnt:
                tags_cnt[tag] = {"count": 0,"samples": []}
            tags_cnt[tag]["count"] += 1
            tags_cnt[tag]["samples"].append(ref)
    sorted_tags = {k:v for k,v in sorted(tags_cnt.items(), key=lambda x: x[1]["count"], reverse=True)if v["count"]>MIN_PAGES}            
    for tag in sorted_tags:
        sorted_tags[tag]["samples"] = random.sample(sorted_tags[tag]["samples"], min(20,len(sorted_tags[tag]["samples"])))
    json.dump(sorted_tags, open(os.path.join(out_dir,"tags.json"), "w"), indent=4)
    print(sorted_tags.keys())
    return 

if __name__ == "__main__":
    data_path = "./cve_data/cve2ref.json"
    out_dir = "./analysis_data"
    stats = check_base_statistic(data_path,out_dir,start_year=2024,end_year=2025)
  