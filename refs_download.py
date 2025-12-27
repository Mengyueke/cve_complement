import json
import argparse
from crawler.ref_crawler import UnifiedCrawler

if __name__ == "__main__":
    # 1. 配置
    parser = argparse.ArgumentParser()
    parser.add_argument('--github_token',default='./github_token.txt')
    parser.add_argument('--ref_path', default="./data/reference/cve2ref.json")
    parser.add_argument('--out_path', default="./data/crawler_data/ref_crawled.json")
    args = parser.parse_args()
    GITHUB_TOKEN = open(args.github_token, "r").read().strip()
    
    # 2. 初始化
    print("Initializing Crawler...")
    crawler = UnifiedCrawler(github_token=GITHUB_TOKEN)
    cve2ref = json.load(open(args.ref_path))
    ref2cve = {}
    urls_to_crawl = []
    for cve_id, refs in cve2ref.items():
        for ref in refs:
            url = ref.get("url")
            tags = ref.get("tags", "")
            if url and "exploit" in tags:
                urls_to_crawl.append(url)
                ref2cve[url] = cve_id
    
    # 先取一部分验证
    urls_to_crawl = urls_to_crawl[:200]
    # 3. 执行
    print("Starting crawl...")
    data = crawler.run(urls_to_crawl)
    
    # 4. 保存
    with open(args.out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"\nAll done! Saved {len(data)} records to {args.out_path}")