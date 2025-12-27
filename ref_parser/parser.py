import json
import re
from typing import Dict, List, Any
from .model import LocalModel,OpenAIModel

class VulnerabilityParser:
    def __init__(self, use_local=False):
        # 根据配置选择模型
        self.llm = LocalModel() if use_local else OpenAIModel()

    def _clean_json_output(self, responses: List[str]) -> List[Dict]:
        """复用 model.py 中的清洗逻辑，这里做一个简单的包装"""
        return self.llm.load_res(responses)

    def extract_basic_info(self, raw_data_list: List[Dict]) -> List[Dict]:
        """
        提取基础信息（Solution, Patch, 后果, 影响范围）
        只处理 Markdown 文本内容
        """
        prompts = []
        for item in raw_data_list:
            content = item.get("markdown", "") # 截断防止过长
            
            prompt_content = f"""
            你是一个网络安全专家。请分析以下漏洞描述文本，提取关键信息。
            
            待分析文本：
            {content}
            
            请输出 JSON 格式，包含以下字段：
            1. "asset": 影响资产（受影响的组件、版本、资产名称、供应商）。
            2. "consequences": 造成的后果（如RCE、DoS、信息泄露等）。
            3. "solution": 修复方案或缓解措施。
            4. "patch": 补丁信息（commit ID、下载链接或版本号）。
            
            如果文中没有提到某项信息，请填 null。不要输出多余的分析过程，只输出 JSON。
            """
            
            messages = [
                {"role": "system", "content": "你是一个专业的漏洞分析助手，只输出JSON格式。"},
                {"role": "user", "content": prompt_content}
            ]
            prompts.append(messages)

        # 批量调用模型
        print(f"[*] 正在提取 {len(prompts)} 条数据的基础信息...")
        responses = self.llm.get_response(prompts, use_tqdm=True)
        return self._clean_json_output(responses)

    def _ocr_process(self, image_path: str) -> str:
        """
        OCR识别占位符，后续接入 OCR 库进行图片文字识别
        """
        # print(f"[*] 正在对图片进行OCR: {image_path}")
        # 这里仅作演示，实际需要调用 OCR 库
        return ""

    def _crawl_link(self, url: str) -> str:
        """
        [跳转爬取占位符] 实际生产中这里接入爬虫去获取外部链接内容
        """
        # print(f"[*] 正在抓取外部链接: {url}")
        return ""

    def extract_exp_poc(self, raw_data_list: List[Dict]) -> List[Dict]:
        """
        功能2：提取 EXP 和 POC 代码
        策略：
        1. 优先从 Markdown 文本中提取代码块、HTTP 请求。
        2. 如果文本中提取不到，检查是否存在图片，提示模型是否需要OCR（此处模拟逻辑）。
        3. 如果文本和图片都无效，检查是否有外部链接（github/exploit-db），提示是否需要跳转。
        """
        prompts = []
        
        # 预处理数据，构建 Prompt
        for item in raw_data_list:
            content = item.get("markdown", "")[:20000]
            images = item.get("media", {}).get("images", [])
            # 提取文中所有的 http 链接作为潜在跳转目标
            links = re.findall(r'(https?://[^\s\)]+)', content)
            
            prompt_content = f"""
            你是一个漏洞利用开发专家。请分析以下安全报告，提取 Proof of Concept (PoC) 或 Exploit (EXP)。

            主要关注点：
            1. HTTP 请求包（Raw Request）。
            2. 脚本代码（Python, Bash, etc.）。
            3. 具体的 Payload 字符串。
            
            待分析文本：
            {content}
            
            附件图片列表：{json.dumps(images)}
            文中链接列表：{json.dumps(links)}

            请输出 JSON 格式，包含以下字段：
            - "has_poc": boolean, 是否直接找到了POC/EXP。
            - "poc_content": string, 具体的代码或请求包内容。
            - "poc_type": string, 类型 (e.g., "http_request", "python_script", "bash_command")。
            - "recommend_action": string, 如果文本中没有代码，但图片看起来像截图（如含有 terminal, request），或者有 github 链接，请建议下一步操作。可选值: "none", "ocr_image", "crawl_link"。
            - "target_source": string, 建议操作的具体目标（图片路径或URL）。

            如果文本中直接找到了代码，recommend_action 填 "none"。只输出 JSON。
            """
            
            messages = [
                {"role": "system", "content": "你是一个漏洞EXP提取助手，只输出JSON格式。"},
                {"role": "user", "content": prompt_content}
            ]
            prompts.append(messages)

        print(f"[*] 正在提取 {len(prompts)} 条数据的 EXP/POC...")
        initial_responses = self.llm.get_response(prompts, use_tqdm=True)
        parsed_results = self._clean_json_output(initial_responses)
        
        # --- 二次处理逻辑 (OCR / 跳转) ---
        final_results = []
        
        # 这一步通常不能并行（或者需要写成复杂的异步），为了演示逻辑，这里用简单的循环处理需要二次分析的项
        # 如果模型判断需要 OCR 或 爬取，我们在这里进行“补救”
        
        secondary_prompts = []
        secondary_indices = [] # 记录需要二次处理的索引
        
        for idx, res in enumerate(parsed_results):
            action = res.get("recommend_action")
            target = res.get("target_source")
            
            # 如果模型认为已经提取到了，直接使用
            if res.get("has_poc") and len(str(res.get("poc_content"))) > 10:
                final_results.append(res)
                continue
            
            # 如果模型建议 OCR (即文本没代码，但有截图)
            if action == "ocr_image" and target:
                print(f"[Deep Analysis] 触发 OCR 流程: {target}")
                ocr_text = self._ocr_process(target)
                # 如果有真实的 OCR 结果，将结果放入 Prompt 再次让 LLM 提取
                if ocr_text:
                    new_prompt = f"这是从图片 {target} 中 OCR 识别出的文本，请从中提取 POC 代码：\n{ocr_text}"
                    secondary_prompts.append([{"role":"user", "content": new_prompt}])
                    secondary_indices.append(idx)
                    continue

            # 如果模型建议跳转 (即文本没代码，但指向了 github)
            if action == "crawl_link" and target:
                print(f"[Deep Analysis] 触发页面跳转流程: {target}")
                page_content = self._crawl_link(target)
                # 如果抓取到了内容，再次提取
                if page_content:
                    new_prompt = f"这是链接 {target} 的页面内容，请从中提取 POC 代码：\n{page_content[:10000]}"
                    secondary_prompts.append([{"role":"user", "content": new_prompt}])
                    secondary_indices.append(idx)
                    continue
            
            # 如果没有后续操作，就保存当前结果
            final_results.append(res)

        # 处理二次请求 (如果有)
        if secondary_prompts:
            print(f"[*] 正在进行二次深度提取 ({len(secondary_prompts)} 条)...")
            secondary_responses = self.llm.get_response(secondary_prompts)
            clean_secondary = self._clean_json_output(secondary_responses)
            
            # 将二次结果合并回去 (实际应用中可能需要更复杂的合并逻辑)
            for i, result in enumerate(clean_secondary):
                # 这里简单覆盖，实际可能需要保留 metadata
                original_idx = secondary_indices[i]
                # 保持原来的索引顺序稍显麻烦，这里简单 append，实际业务建议用 Dict 映射 ID
                final_results.append(result)

        return final_results

    def run(self, crawler_data_path):
        """主入口"""
        with open(crawler_data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 1. 提取基础信息
        basic_infos = self.extract_basic_info(data)
        
        # 2. 提取 EXP/POC (含高级逻辑)
        exp_infos = self.extract_exp_poc(data)

        # 3. 合并结果
        merged_data = []
        for i, item in enumerate(data):
            merged_item = {
                "source_url": item.get("url"),
                "base_info": basic_infos[i] if i < len(basic_infos) else {},
                "exp_poc": exp_infos[i] if i < len(exp_infos) else {} # 注意：如果exp_infos顺序打乱了需要用id匹配，这里假设是顺序的
            }
            merged_data.append(merged_item)
            
        return merged_data

if __name__ == "__main__":
    
    parser = VulnerabilityParser(use_local=False) # 使用 OpenAIModel 类 (支持异步)
    