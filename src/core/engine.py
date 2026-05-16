import asyncio
from typing import List, Dict, Optional, Any
import os
import time
import re
import httpx
from google import genai
from core.history import HistoryManager
from channels.base import BaseChannel
from utils.config import DEFAULT_MODEL, INTRO_PHRASE, HERMES_PREFIX, OWNER_INPUT_WAIT, \
    CONVERSATION_END_WAIT, POLL_INTERVAL, RUNTIME_TIMEOUT, TOOL_WAIT, \
    HERMES_API_URL

class ChatEngine:
    def __init__(self, channel: BaseChannel, chat_name: str, task: str, chat_id: Optional[str] = None, model_name: str = DEFAULT_MODEL, api_key: Optional[str] = None) -> None:
        self.channel = channel
        self.target_chat = chat_name
        self.target_chat_id = chat_id
        self.task_description = task
        self.model_name = model_name
        self.history = HistoryManager(chat_name)
        self.client = genai.Client(api_key=api_key)
        
        etiquette_path = os.path.join(os.path.dirname(__file__), "prompts/etiquette.md")
        with open(etiquette_path, "r", encoding="utf-8") as f:
            self.etiquette = f.read()

        prompt_path = os.path.join(os.path.dirname(__file__), "prompts/engine.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            self.system_prompt_template = f.read()
            
        analyzer_path = os.path.join(os.path.dirname(__file__), "prompts/analyzer.md")
        with open(analyzer_path, "r", encoding="utf-8") as f:
            self.analyzer_prompt_template = f.read()
            
        self.state = {
            "sent_messages": [], 
            "last_processed_msg": "", 
            "exit_at": None, 
            "final_report": None,
            "service_target": "對方",
            "task_start_time": None,
            "spam_limit": 3
        }

    async def _generate_image_locally(self, query: str) -> str:
        model_id = "imagen-4.0-generate-001"
        self.history.write_log(f"LOCAL_IMAGE_GEN: Generating image using {model_id} for query: {query}")
        
        timestamp = time.strftime("%Y%m%d_%H%M")
        import hashlib
        hash_str = hashlib.md5(f"{query}_{model_id}".encode()).hexdigest()[:4]
        filename = f"image_{timestamp}_{hash_str}.png"
        
        safe_chat_id = self.target_chat_id or self.target_chat.replace(" ", "_")
        cache_dir = os.path.expanduser(f"~/.chat-agent/file-cache/{safe_chat_id}")
        os.makedirs(cache_dir, exist_ok=True)
        file_path = os.path.join(cache_dir, filename)
        
        response = self.client.models.generate_images(model=model_id, prompt=query)
        response.generated_images[0].image.save(file_path)
        self.history.write_log(f"LOCAL_IMAGE_GEN: Saved to {file_path}")
        return file_path

    async def analyze_context(self, context_lines: List[str]) -> None:
        prompt = self.analyzer_prompt_template
        prompt = prompt.replace("{{task_description}}", self.task_description)
        prompt = prompt.replace("{{context_lines}}", "\n".join(context_lines))
        # 讓 Analyzer 也使用佔位符，或者讓它知道 Owner 是誰（在對話紀錄中 Junyu 出現的地方）
        # 由於我們希望 Junyu 被當作一般人，這裡傳入一個 AI 幾乎不會在對話中看到的標籤
        prompt = prompt.replace("{{OWNER_NAME}}", "__INTERNAL_OWNER_LABEL__")

        try:
            response = self.client.models.generate_content(model=self.model_name, contents=prompt)
            import json
            clean_text = re.sub(r"```json\s*(.*?)\s*```", r"\1", response.text, flags=re.DOTALL).strip()
            data = json.loads(clean_text)
            
            if data.get("service_target"):
                self.state["service_target"] = data["service_target"]
            if data.get("task_start_time"):
                self.state["task_start_time"] = data["task_start_time"]
            if data.get("is_started") is not None:
                self.state["is_started"] = data["is_started"]
            
            self.history.write_log(f"ANALYSIS: target='{self.state['service_target']}', start='{self.state['task_start_time']}', is_started={self.state.get('is_started')}")
        except Exception as e:
            self.history.write_log(f"Warning: Failed to analyze context: {e}")
        
    def _build_prompt(self, msgs: List[Dict[str, Any]], context_lines: List[str]) -> str:
        pruned_context = context_lines
        if self.state.get("task_start_time"):
            start_marker = self.state["task_start_time"]
            for i, line in enumerate(context_lines):
                if start_marker in line:
                    pruned_context = context_lines[i:]
                    break

        recent_context = pruned_context[-10:]
        intro_already_done = any("Hermes" in line and ("AI代理" in line or "AI 代理" in line or "AI Proxy" in line) for line in recent_context)
        
        intro_instruction = ("你已經在之前的對話中自我介紹過了，現在請直接針對對方的最新訊息進行回覆，嚴禁再次重複自我介紹。" if intro_already_done else f"這是你與對方的第一次對話。請務必先進行自我介紹，開場白應固定為：『{INTRO_PHRASE}』。")
        
        available_files = []
        now = time.time()
        one_day_sec = 24 * 60 * 60
        for m in msgs:
            media = m.get("media")
            if media and media.get("local_path"):
                path = media["local_path"]
                if os.path.exists(path):
                    if (now - os.path.getmtime(path)) <= one_day_sec:
                        ftype = media.get("type", "file")
                        fname = media.get("name") or os.path.basename(path)
                        available_files.append(f"- {ftype}: {fname}, 路徑: {path}")
        
        file_context = ""
        if available_files:
            file_context = "\n## 可用的本地檔案資源 ##\n" + "\n".join(available_files) + "\n"
            file_context += "你可以使用 [TOOL_ACCESS_NEEDED, tool=\"terminal\", query=\"...\"] 來操作這些檔案。\n"

        prompt = self.system_prompt_template
        prompt = prompt.replace("{{service_target}}", self.state['service_target'])
        status_note = "\n**注意：此任務已在進行中。請檢查歷史紀錄，避免重複執行。**\n" if self.state.get("is_started") else ""
        prompt = prompt.replace("{{task_description}}", f"{status_note}{self.task_description}")
        prompt = prompt.replace("{{intro_instruction}}", intro_instruction)
        prompt = prompt.replace("{{HERMES_PREFIX}}", HERMES_PREFIX)
        prompt = prompt.replace("{{etiquette}}", self.etiquette)
        prompt = prompt.replace("{{INTRO_PHRASE}}", INTRO_PHRASE)
        # 讓 AI 在系統提示詞中直接看到佔位符，這樣它輸出時也會使用佔位符
        # prompt = prompt.replace("{{OWNER_NAME}}", "Owner") 
        prompt = prompt.replace("{{context_lines}}", "\n".join(pruned_context))
        prompt = prompt.replace("{{file_context}}", file_context) 
        prompt = prompt.replace("{{SPAM_LIMIT}}", str(self.state["spam_limit"]))
        return prompt

    def _parse_response(self, full_text: str) -> Dict[str, Any]:
        waiting_match = re.search(r'\[WAIT_FOR_TARGET_REPLY(?:,\s*reason="([^"]+)")?\]', full_text)
        owner_input_match = re.search(r'\[OWNER_INPUT_NEEDED,\s*reason="([^"]+)"(?:,\s*summary="([^"]+)")?\]', full_text)
        convo_ended_match = re.search(r'\[CONVERSATION_ENDED,\s*summary="([^"]+)"\]', full_text)
        tool_match = re.search(r'\[TOOL_ACCESS_NEEDED,\s*tool="([^"]+)",\s*query="([^"]+)"\]', full_text)
        image_matches = re.findall(r'\[IMAGE,\s*([^\]]+)\]', full_text)
        
        reply_text = full_text
        reply_text = re.sub(r'\[OWNER_INPUT_NEEDED,.*?\]', '', reply_text)
        reply_text = re.sub(r'\[CONVERSATION_ENDED,.*?\]', '', reply_text)
        reply_text = re.sub(r'\[TOOL_ACCESS_NEEDED,.*?\]', '', reply_text)
        reply_text = re.sub(r'\[IMAGE,.*?\]', '', reply_text)
        reply_text = re.sub(r'\[WAIT_FOR_TARGET_REPLY.*?\]', '', reply_text).strip()
        
        forbidden_keywords = r"Hermes|代理人|Owner|委託人|監控|系統|逾時|時限|進度|執行計畫"
        leak_pattern = rf"\[.*?(?:{forbidden_keywords}).*?\]"
        reply_text = re.sub(leak_pattern, '', reply_text, flags=re.IGNORECASE).strip()

        return {
            "text": reply_text,
            "is_waiting": waiting_match is not None,
            "waiting_reason": waiting_match.group(1) if waiting_match else None,
            "owner_input_needed": owner_input_match.group(1) if owner_input_match else None,
            "summary": (convo_ended_match.group(1) if convo_ended_match else 
                        owner_input_match.group(2) if (owner_input_match and owner_input_match.lastindex is not None and owner_input_match.lastindex >= 2) else None),
            "conversation_ended": convo_ended_match is not None,
            "tool_needed": {"tool": tool_match.group(1), "query": tool_match.group(2)} if tool_match else None,
            "images": [img.strip() for img in image_matches]
        }

    async def execute_hermes_tool(self, tool_name: str, query: str) -> str:
        toolset_map = {"web_search": "web", "browser": "browser", "terminal": "terminal", "vision_analyze": "vision", "read_file": "file"}
        target_toolset = toolset_map.get(tool_name, tool_name)
        url = f"{HERMES_API_URL}/v1/chat/completions"
        payload = {
            "model": "hermes-agent",
            "toolsets": [target_toolset],
            "messages": [
                {"role": "system", "content": "You are a minimalist tool executor. Return ONLY raw output."},
                {"role": "user", "content": f"Execute tool '{tool_name}' for query: '{query}'"}
            ],
            "stream": False
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    def _check_spamming(self, msgs: List[Dict[str, Any]]) -> None:
        count = 0
        for m in reversed(msgs):
            if m.get("sender") != "Hermes": break
            text = m.get("text", "").strip()
            if not (text.startswith("[系統") or text.startswith("[TOOL")): count += 1
        if count >= self.state["spam_limit"]:
            raise Exception(f"Spam limit reached ({self.state['spam_limit']}).")

    async def generate_and_send_reply(self, msgs: List[Dict[str, Any]]) -> None:
        max_turns = 3
        current_turn = 0
        while current_turn < max_turns:
            try:
                context_lines = self.history.get_full_context(msgs, self.state["sent_messages"])
                prompt = self._build_prompt(msgs, context_lines)
                response = self.client.models.generate_content(model=self.model_name, contents=prompt)
                result = self._parse_response(str(getattr(response, 'text', '')).strip())
                
                text_to_send = result["text"]
                if text_to_send and text_to_send in self.state["sent_messages"]:
                    text_to_send = None
                if not text_to_send and result.get("images"):
                    text_to_send = "傳送圖片如下："

                if text_to_send and text_to_send not in self.state["sent_messages"]:
                    self._check_spamming(msgs)
                    # 發送時，Engine 傳出的 text 可能包含 {{OWNER_NAME}}
                    await self.channel.send_message(text_to_send)
                    self.history.write_log(f"SENT: {text_to_send}")
                    self.state["sent_messages"].append(text_to_send.strip())
                
                for img_path in result.get("images", []):
                    await self.channel.send_image(img_path)
                    self.history.write_log(f"SENT IMAGE: {img_path}")
                    self.state["sent_messages"].append(f"[IMAGE: {img_path}]")
                
                latest_msgs = await self.channel.extract_messages()
                if latest_msgs: self.state["last_processed_msg"] = latest_msgs[-1].get("text", "")
                
                if result["summary"]:
                    print(f"\n[REPORT]\n{result['summary']}\n[/REPORT]")

                if result["is_waiting"]: break
                if result["owner_input_needed"]:
                    self.state.update({"exit_at": time.time() + OWNER_INPUT_WAIT, "final_report": f"[OWNER_INPUT_NEEDED] {result['owner_input_needed']}"})
                    break
                if result["conversation_ended"]:
                    self.state.update({"exit_at": time.time() + CONVERSATION_END_WAIT, "final_report": f"[CONVERSATION_ENDED] {result['summary'] or 'Mission complete.'}"})
                    break
                if result["tool_needed"]:
                    tool_name = result["tool_needed"]["tool"]
                    query = result["tool_needed"]["query"]
                    try:
                        tool_output = await self._generate_image_locally(query) if tool_name == "image_gen" else await self.execute_hermes_tool(tool_name, query)
                        self.state["sent_messages"].append(f"[系統通知] 工具執行成功。結果為: {tool_output}")
                        current_turn += 1
                        msgs = await self.channel.extract_messages()
                        continue 
                    except Exception: break
                break
            except Exception as e:
                self.history.write_log(f"Error: {e}")
                self.state["final_report"] = str(e)
                break

    async def run(self) -> Optional[str]:
        start_time = time.time()
        await self.channel.bring_to_front()
        selection = await self.channel.select_chat(self.target_chat, self.target_chat_id)
        if selection.get("status") != "success": return selection.get("error")
        
        msgs = await self.channel.extract_messages()
        if msgs is None: return
        context_lines = self.history.get_full_context(msgs, [])
        await self.analyze_context(context_lines)
        self.state.update(self.history.rebuild_state(msgs or [], self.task_description))
        
        try:
            await self.generate_and_send_reply(msgs or [])
        except Exception: return self.state.get("final_report")

        while True:
            if time.time() - start_time > RUNTIME_TIMEOUT:
                self.state["final_report"] = "[SILENT_RESTART_NEEDED]"
                break
            if self.state.get("exit_at") and time.time() >= self.state["exit_at"]: break
            try:
                msgs = await self.channel.extract_messages()
                if msgs:
                    latest = msgs[-1]
                    # 只有真的 Hermes（有前綴的）才被視為自己
                    is_hermes = latest.get("sender") == "Hermes"
                    is_new = latest["text"].strip() != self.state.get("last_processed_msg", "").strip()
                    if not is_hermes and is_new:
                        if self.state.get("exit_at"): self.state["exit_at"] = None
                        await self.generate_and_send_reply(msgs)
            except Exception: break
            await asyncio.sleep(POLL_INTERVAL)
        return self.state.get("final_report")
