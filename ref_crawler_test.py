import asyncio
import json
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from bs4 import BeautifulSoup


async def crawl_ref(url: str, out_path: str):
    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
    )

    run_config = CrawlerRunConfig(
        word_count_threshold=50,
        wait_for_images=True,        # 等图片节点出现即可
        remove_overlay_elements=True,
        screenshot=False,
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

        if not result.success:
            print(f"[!] Failed: {url}")
            return

        # ========== 正文 ==========
        text = result.markdown or ""

        # ========== 图片 URL ==========
        soup = BeautifulSoup(result.cleaned_html, "lxml")

        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue

            images.append({
                "url": src,
                "alt": img.get("alt", ""),
                "context": img.parent.get_text(strip=True)[:200]
            })

        data = {
            "ref_url": url,
            "text": text,
            "images": images
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[+] Extracted {len(images)} image URLs from {url}")


if __name__ == "__main__":
    asyncio.run(
        crawl_ref(
            "https://research.checkpoint.com/2025/gachiloader-node-js-malware-with-api-tracing/",
            "ref_result.json"
        )
    )
