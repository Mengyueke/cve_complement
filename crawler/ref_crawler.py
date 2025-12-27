import asyncio
import re
import json
import base64
import os
import aiohttp
from typing import Dict, Any, List

# 引入 crawl4ai
from crawl4ai import AsyncWebCrawler,DefaultMarkdownGenerator,CrawlerRunConfig

class AsyncGitHubExtractor:
    """
    [内部组件] GitHub API 提取器 (保持异步)
    """
    def __init__(self, token: str = None):
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Crawl4AI-GitHub-Plugin"
        }
        if token:
            self.headers["Authorization"] = f"token {token}"

    def _extract_images(self, text: str, context_window: int = 100) -> List[Dict[str, str]]:
        """
        提取文本中的图片链接及其上下文。
        
        Args:
            text: 原始文本
            context_window: 截取图片前后多少个字符作为上下文，默认为 100
            
        Returns:
            List[Dict]: 包含 'url' (图片链接) 和 'context' (上下文内容) 的字典列表
        """
        if not text:
            return []

        # Markdown 图片正则: ![alt](url)
        # group(1) 捕获 URL
        md_pattern = r"!\[.*?\]\((.*?)\)"
        
        # HTML 图片正则: <img src="url">
        # group(1) 捕获 URL
        html_pattern = r'<img\s+[^>]*src=["\']([^"\']+)["\']'

        results = []

        # 定义一个内部函数来处理正则匹配
        def process_pattern(pattern):
            # 使用 finditer 而不是 findall，以便获取位置信息
            for match in re.finditer(pattern, text):
                image_url = match.group(1)
                start, end = match.span() # 获取整个图片标签在 text 中的起始和结束位置

                # 计算上下文的切片范围
                # max(0, ...) 防止索引越界变为负数
                ctx_start = max(0, start - context_window)
                # min(len, ...) 防止索引超出文本长度
                ctx_end = min(len(text), end + context_window)

                # 截取上下文
                context_text = text[ctx_start:ctx_end]

                # 可选：如果你希望上下文不包含图片标签本身，可以在这里做字符串替换
                # context_text = context_text.replace(match.group(0), "[IMAGE]") 

                results.append({
                    "url": image_url,
                    "context": context_text,
                    "source_type": "markdown" if pattern == md_pattern else "html"
                })

        # 分别处理两种模式
        process_pattern(md_pattern)
        process_pattern(html_pattern)

        return results


    def _extract_urls(self, text: str, context_window: int = 100) -> List[Dict[str, str]]:
        """
        提取文本中的 URL 及其上下文。
        会自动处理 Markdown 链接和纯文本 URL，并避免重复提取。
        
        Args:
            text: 原始文本
            context_window: 截取 URL 前后多少个字符作为上下文
            
        Returns:
            List[Dict]: 包含 'url', 'context', 'anchor_text' 的字典列表
        """
        if not text:
            return []

        results = []
        
        # 用来记录已经被 Markdown 模式匹配过的位置区间，防止纯 URL 模式二次匹配
        # 格式: List[Tuple[int, int]] -> [(start, end), ...]
        processed_spans = []

        # 1. Markdown 链接正则: [text](url)
        # (?<!\!) 是“负向零宽断言”，确保 '[' 前面不是 '!'，从而排除图片 ![alt](url)
        md_pattern = r'(?<!\!)\[([^\]]*)\]\((https?://[^)]+)\)'
        
        # 2. 纯 URL 正则: http:// 或 https:// 开头
        # 允许字母数字、标点符号，直到遇到空格或换行
        raw_pattern = r'https?://[a-zA-Z0-9./?=&_%-]+'

        def get_context(start_pos, end_pos):
            """辅助函数：根据位置截取上下文"""
            ctx_start = max(0, start_pos - context_window)
            ctx_end = min(len(text), end_pos + context_window)
            return text[ctx_start:ctx_end]

        # --- 第一步：优先匹配 Markdown 链接 ---
        for match in re.finditer(md_pattern, text):
            anchor_text = match.group(1) # 链接文字，如 [Google] 中的 Google
            url = match.group(2)         # URL
            start, end = match.span()
            
            # 记录这个区间已经被处理了
            processed_spans.append((start, end))

            results.append({
                "url": url,
                "anchor_text": anchor_text, # Markdown 链接有锚文本
                "context": get_context(start, end),
                "type": "markdown_link"
            })

        # --- 第二步：匹配纯文本 URL ---
        for match in re.finditer(raw_pattern, text):
            url = match.group(0)
            start, end = match.span()

            # 检查重叠：如果这个 URL 的位置在已经被 Markdown 处理过的区间内，则跳过
            # 例如 [Link](http://a.com) 中的 http://a.com 不应被再次作为纯文本提取
            is_overlapping = False
            for p_start, p_end in processed_spans:
                if start >= p_start and end <= p_end:
                    is_overlapping = True
                    break
            
            if is_overlapping:
                continue

            results.append({
                "url": url,
                "anchor_text": None, # 纯 URL 没有锚文本
                "context": get_context(start, end),
                "type": "raw_url"
            })

        return results


    def _parse_url(self, url: str):
        if "gist.github.com" in url:
            match = re.search(r"gist\.github\.com/([^/]+)/([a-f0-9]+)", url)
            if match:
                return {"type": "gist", "id": match.group(2)}
        
        pattern = r"github\.com/([^/]+)/([^/]+)/(blob|issues|commit|pull|releases/tag)/(.+)"
        match = re.search(pattern, url)
        if not match:
            return None
        return {
            "owner": match.group(1), "repo": match.group(2),
            "type": match.group(3), "id_or_path": match.group(4)
        }

    async def _fetch(self, session, url, params=None):
        try:
            async with session.get(url, headers=self.headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    print(f"[Warn] 404 Not Found: {url}")
                    return None
                else:
                    print(f"[Error] API Status {response.status}: {url}")
                    return None
        except Exception as e:
            print(f"[Exception] Fetch error: {e}")
            return None

    async def extract(self, url: str) -> Dict[str, Any]:
        meta = self._parse_url(url)
        if not meta:
            return {"error": "Invalid GitHub URL", "url": url}

        ref_type = meta.get('type')
        result_data = {
            "url": url, "source": "github_api", "type": ref_type,
            "markdown": "", "media": {"images": []}
        }

        async with aiohttp.ClientSession() as session:
            # 简化逻辑：根据类型分发请求
            if ref_type == 'gist':
                data = await self._fetch(session, f"https://api.github.com/gists/{meta['id']}")
                if data:
                    desc = data.get('description', 'No description')
                    files_md = [f"### File: {k}\n```\n{v.get('content','')}\n```" for k,v in data.get('files',{}).items()]
                    result_data["markdown"] = f"# Gist: {desc}\n\n" + "\n\n".join(files_md)

            elif ref_type == 'issues':
                # issues 和 pull requests 的 ID 处理需要注意去掉 #comment
                clean_id = meta['id_or_path'].split('/')[0].split('#')[0]
                api_url = f"https://api.github.com/repos/{meta['owner']}/{meta['repo']}/issues/{clean_id}"
                data = await self._fetch(session, api_url)
                if data:
                    title, body = data.get('title', ''), data.get('body', '') or ''
                    result_data["markdown"] = f"# Issue: {title}\n\n{body}"
                    result_data["media"]["images"] = self._extract_images(body)
                    result_data["links"] = self._extract_urls(body)

            elif ref_type == 'commit':
                api_url = f"https://api.github.com/repos/{meta['owner']}/{meta['repo']}/commits/{meta['id_or_path']}"
                data = await self._fetch(session, api_url)
                if data:
                    msg = data.get('commit', {}).get('message', '')
                    patches = [f"### Modified: {f['filename']}\n```diff\n{f.get('patch','[Binary]')}\n```" for f in data.get('files', [])]
                    result_data["markdown"] = f"# Commit: {meta['id_or_path'][:7]}\n\n## Message\n{msg}\n\n## Changes\n" + "\n\n".join(patches)

            elif ref_type == 'pull':
                base_url = f"https://api.github.com/repos/{meta['owner']}/{meta['repo']}/pulls/{meta['id_or_path']}"
                pr_data = await self._fetch(session, base_url)
                files_data = await self._fetch(session, f"{base_url}/files")
                if pr_data:
                    title, body = pr_data.get('title', ''), pr_data.get('body', '') or ''
                    patches = [f"### File: {f['filename']}\n```diff\n{f.get('patch','')}\n```" for f in (files_data or [])]
                    result_data["markdown"] = f"# PR: {title}\n\n## Description\n{body}\n\n## Changes\n" + "\n\n".join(patches)
                    result_data["media"]["images"] = self._extract_images(body)
                    result_data["links"] = self._extract_urls(body)


            elif ref_type == 'blob':
                # 简单解析：blob/ref/path
                parts = meta['id_or_path'].split('/', 1)
                if len(parts) == 2:
                    ref, file_path = parts[0], parts[1]
                    api_url = f"https://api.github.com/repos/{meta['owner']}/{meta['repo']}/contents/{file_path}"
                    data = await self._fetch(session, api_url, params={"ref": ref})
                    if data and data.get('encoding') == 'base64':
                        try:
                            content = base64.b64decode(data['content']).decode('utf-8', errors='ignore')
                            result_data["markdown"] = f"# File: {file_path}\n\n```\n{content}\n```"
                            if file_path.endswith('.md'):
                                result_data["media"]["images"] = self._extract_images(content)
                                result_data["links"] = self._extract_urls(content)
                        except Exception:
                            result_data["markdown"] = "Error decoding file content"

            elif ref_type == 'releases/tag':
                api_url = f"https://api.github.com/repos/{meta['owner']}/{meta['repo']}/releases/tags/{meta['id_or_path']}"
                data = await self._fetch(session, api_url)
                if data:
                    result_data["markdown"] = f"# Release: {data.get('name', meta['id_or_path'])}\n\n{data.get('body', '')}"

        return result_data


class UnifiedCrawler:
    """
    统一爬虫控制器 (对外提供同步接口)
    """
    def __init__(self, github_token: str = None):
        self.github_extractor = AsyncGitHubExtractor(token=github_token)
        self.md_generator = DefaultMarkdownGenerator(
            options={
                "ignore_links": True,
                "ignore_images":True,
                "body_width": 80
            }
        )
        self.config = CrawlerRunConfig(
            markdown_generator=self.md_generator
        )
    
    async def _process_urls_async(self, urls: List[str]):
        """
        内部核心逻辑：异步并发处理所有 URL
        """
        results = []
        browser_urls = []
        github_tasks = []

        # 1. 分流 URL
        for url in urls:
            if "github.com" in url and any(x in url for x in ["/blob/", "/issues/", "/commit/", "/pull/", "/releases/", "gist.github.com"]):
                print(f"[GitHub API] Processing: {url}")
                github_tasks.append(self.github_extractor.extract(url))
            else:
                browser_urls.append(url)
        
        # 2. 并发执行 GitHub 任务
        if github_tasks:
            github_results = await asyncio.gather(*github_tasks)
            results.extend(github_results)
        
        # 3. 并发执行 Web 爬取任务 (crawl4ai)
        if browser_urls:
            print(f"\n[Crawl4AI] Starting browser for {len(browser_urls)} URLs...")
            async with AsyncWebCrawler(verbose=True) as crawler:
                tasks = [crawler.arun(url=url,config=self.config) for url in browser_urls]
                # 并发等待所有爬虫结果
                crawl_results = await asyncio.gather(*tasks)
                
                for url, result in zip(browser_urls, crawl_results):
                    if result.success:
                        results.append({
                            "url": url,
                            "source": "crawl4ai_browser",
                            "type": "webpage",
                            "markdown": result.markdown,
                            "media": result.media,
                            "links": result.links
                        })
                    else:
                        print(f"   Failed: {url} - {result.error_message}")
                        results.append({"url": url, "error": result.error_message})

        return results

    def run(self, urls: List[str]) -> List[Dict]:
        """
        【同步接口】
        标准的 Python 入口，自动管理 Event Loop。
        """
        return asyncio.run(self._process_urls_async(urls))

