"""模型推理类"""
import os
import json
from transformers import AutoTokenizer
import torch
from vllm import LLM, SamplingParams
import re
import asyncio
from typing import List, Dict, Any
from openai import AsyncOpenAI


class LocalModel:
    """加载本地大模型进行推理"""
    def __init__(self,model_path='/data1/mengyueke/Qwen3-8B') -> None:
        self.llm = None
        self.llm = LLM(
            model_path,
            max_model_len=32768,
            tensor_parallel_size=torch.cuda.device_count(),
            gpu_memory_utilization=0.9,
            )
        self.sampling_params = SamplingParams(temperature=0, top_p=0.95 ,max_tokens=10000)
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
    
    def get_response(self,messages,use_tqdm=True,enable_thinking=True):
        # 保证不超过最大长度
        prompts = []
        max_len = int(self.llm.llm_engine.model_config.max_model_len*0.9)
        
        for message in messages:
            prompt = self.tokenizer.apply_chat_template(
                message,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=enable_thinking
            )
            # 按 token 截断
            token_ids = self.tokenizer(prompt)["input_ids"]
            if len(token_ids) > max_len:
                print(f"[WARN] prompt too long ({len(token_ids)} tokens), truncating...")
                token_ids = token_ids[:max_len] 
                token_ids.append(self.tokenizer.eos_token_id)

                # 解码回字符串
                prompt = self.tokenizer.decode(token_ids, skip_special_tokens=False)
            
            prompts.append(prompt)
        
        # print(prompts[1])
        outputs = self.llm.generate(prompts,self.sampling_params,use_tqdm=use_tqdm)
        responses = [output.outputs[0].text for output in outputs]
        return responses

    def load_res(self,res):
        if not isinstance(res,list):
            res = [res]
        # 使用正则表达式匹配第一个 JSON 字典
        json_res = []
        for text in res:
            try:
                text = re.sub(r"<think>[\s\S]*?</think>","",text)
                start_index = text.find('{')
                end_index = text.rfind('}')

                if start_index == -1 or end_index == -1:
                    json_res.append({})
                    continue 
                json_str = text[start_index:end_index + 1]
                json_dict = json.loads(json_str)
                json_res.append(json_dict)
            except Exception as e:
                print(e)
                json_res.append({})
        return json_res
    
class OpenAIModel:
    """
    内部使用异步并发调用 OpenAI API，对外提供同步接口。
    兼容 LocalModel 的调用方式。
    """
    
    def __init__(self, 
                 model_name: str = "deepseek-chat", 
                 api_key: str = "sk-f5e02388353344249da1ac677333d816", 
                 base_url: str = "https://api.deepseek.com", 
                 max_concurrency: int = 20
                 ) -> None:
        
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.max_concurrency = max_concurrency
        # 注意：这里不初始化 client，而是在异步任务里初始化，避免 Event Loop 冲突

    async def _single_request(self, client, semaphore, messages: List[Dict]) -> str:
        """内部使用的异步单条请求函数"""
        async with semaphore:
            try:
                response = await client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0,
                    top_p=0.95
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"[ERROR] {e}")
                return ""

    async def _batch_process(self, messages_list, use_tqdm):
        """内部异步批量处理逻辑"""
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        tasks = [self._single_request(client, semaphore, msg) for msg in messages_list]
        
        if use_tqdm:
            try:
                from tqdm.asyncio import tqdm_asyncio
                # 使用 gather 并发执行
                return await tqdm_asyncio.gather(*tasks)
            except ImportError:
                return await asyncio.gather(*tasks)
        else:
            return await asyncio.gather(*tasks)

    def get_response(self, messages_list: List[List[Dict]], use_tqdm: bool = True, enable_thinking: bool = True) -> List[str]:
        """
        这里使用 asyncio.run() 自动管理事件循环。
        """
        # 这里的 run 会阻塞直到所有并发请求完成
        return asyncio.run(self._batch_process(messages_list, use_tqdm))

    def load_res(self, res):
        if not isinstance(res, list):
            res = [res]
        json_res = []
        for text in res:
            try:
                if not text:
                    json_res.append({})
                    continue
                text = re.sub(r"<think>[\s\S]*?</think>", "", text)
                start = text.find('{')
                end = text.rfind('}')
                if start == -1 or end == -1:
                    json_res.append({})
                    continue
                json_res.append(json.loads(text[start:end+1]))
            except:
                json_res.append({})
        return json_res

if __name__ == "__main__":
    constructor = OpenAIModel()
    messages = []
    for i in range(10,20):
        prompt = f"""请从以下描述中抽取事件及其论元，输出格式为JSON字典，包含事件描述和论元列表，每个论元包含名称和值。"""
        message = [
            {"role":"system","content":"你是一个专业的人工智能助手。"},
            {"role":"user","content":f"给我数字{i}的因数"}
        ]
        messages.append(message)
    responses = constructor.get_response(messages)
    print(responses)