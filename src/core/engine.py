import asyncio
from typing import List, Dict, Optional, Any
import os
import time
import re
import httpx
from google import genai
from core.history import HistoryManager
from channels.base import BaseChannel
from utils.config import DEFAULT_MODEL, OWNER_NAME, INTRO_PHRASE, HERMES_PREFIX, OWNER_INPUT_WAIT, \
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
            "service_target": "對方", # 預設值
            "task_start_time": None,
            "spam_limit": 3 # 統一管理上限
        }

    async def _generate_image_locally(self, query: str) -> str:
        """使用本地 Imagen 4 Standard SDK 生成圖片"""
        model_id = "imagen-4.0-generate-001"
        self.history.write_log(f"LOCAL_IMAGE_GEN: Generating image using {model_id} for query: {query}")
        
        # 建立存檔路徑
        timestamp = time.strftime("%Y%m%d_%H%M")
        import hashlib
        hash_str = hashlib.md5(f"{query}_{model_id}".encode()).hexdigest()[:4]
        filename = f"image_{timestamp}_{hash_str}.png"
        
        safe_chat_id = self.target_chat_id or self.target_chat.replace(" ", "_")
        cache_dir = os.path.expanduser(f"~/.chat-agent/file-cache/{safe_chat_id}")
        os.makedirs(cache_dir, exist_ok=True)
        file_path = os.path.join(cache_dir, filename)
        
        # 調用 SDK
        response = self.client.models.generate_images(
            model=model_id,
            prompt=query
        )
        
        # 儲存圖片
        response.generated_images[0].image.save(file_path)
        self.history.write_log(f"LOCAL_IMAGE_GEN: Saved to {file_path}")
        
        return file_path

    async def analyze_context(self, context_lines: List[str]) -> None:
        """分析對話上下文，識別服務對象與任務起始點"""
        prompt = self.analyzer_prompt_template
        prompt = prompt.replace("{{task_description}}", self.task_description)
        prompt = prompt.replace("{{context_lines}}", "\n".join(context_lines))
        prompt = prompt.replace("{{OWNER_NAME}}", OWNER_NAME)

        try:
            response = self.client.models.generate_content(model=self.model_name, contents=prompt)
            import json
            # 清理 Markdown 代碼塊標記
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
        # 根據 task_start_time 裁切上下文，只保留任務開始後的對話
        pruned_context = context_lines
        if self.state.get("task_start_time"):
            start_marker = self.state["task_start_time"]
            for i, line in enumerate(context_lines):
                if start_marker in line:
                    pruned_context = context_lines[i:]
                    break

        recent_context = pruned_context[-10:]
        intro_already_done = any("Hermes" in line and ("AI代理" in line or "AI 代理" in line or "AI Proxy" in line) 
                                 for line in recent_context)
        
        intro_instruction = ("你已經在之前的對話中自我介紹過了，現在請直接針對對方的最新訊息進行回覆，嚴禁再次重複自我介紹。" 
                             if intro_already_done else 
                             f"這是你與對方的第一次對話。請務必先進行自我介紹，開場白應固定為：『{INTRO_PHRASE}』。")
        
        # 提取可用檔案資訊 (僅限該對話且 24 小時內)
        available_files = []
        now = time.time()
        one_day_sec = 24 * 60 * 60
        
        for m in msgs:
            media = m.get("media")
            if media and media.get("local_path"):
                path = media["local_path"]
                if os.path.exists(path):
                    # 檢查檔案時間
                    mtime = os.path.getmtime(path)
                    if (now - mtime) <= one_day_sec:
                        ftype = media.get("type", "file")
                        fname = media.get("name") or os.path.basename(path)
                        available_files.append(f"- {ftype}: {fname}, 路徑: {path}")
        
        file_context = ""
        if available_files:
            file_context = "\n## 可用的本地檔案資源 ##\n" + "\n".join(available_files) + "\n"
            file_context += "你可以使用 [TOOL_ACCESS_NEEDED, tool=\"terminal\", query=\"...\"] 來操作這些檔案（如解壓縮、安裝套件、列出目錄）。\n"
            file_context += "如果是圖片，你可以使用 [TOOL_ACCESS_NEEDED, tool=\"vision_analyze\", query=\"...\"] 並傳入圖片路徑來分析內容。\n"

        prompt = self.system_prompt_template
        
        # 注入服務對象到任務背景
        prompt = prompt.replace("{{service_target}}", self.state['service_target'])
        
        # 注入任務啟動狀態提示
        status_note = ""
        if self.state.get("is_started"):
            status_note = "\n**注意：此任務已在進行中。請檢查歷史紀錄，確認你是否已經執行過計畫的初期階段，避免重複發送相同的訊息。**\n"
        
        prompt = prompt.replace("{{task_description}}", f"{status_note}{self.task_description}")
        prompt = prompt.replace("{{intro_instruction}}", intro_instruction)
        prompt = prompt.replace("{{HERMES_PREFIX}}", HERMES_PREFIX)
        prompt = prompt.replace("{{etiquette}}", self.etiquette)
        prompt = prompt.replace("{{INTRO_PHRASE}}", INTRO_PHRASE)
        prompt = prompt.replace("{{OWNER_NAME}}", OWNER_NAME)
        prompt = prompt.replace("{{context_lines}}", "\n".join(pruned_context))
        prompt = prompt.replace("{{file_context}}", file_context) 
        prompt = prompt.replace("{{SPAM_LIMIT}}", str(self.state["spam_limit"]))
        
        return prompt

    def _parse_response(self, full_text: str) -> Dict[str, Any]:
        waiting_match = "[WAIT_FOR_TARGET_REPLY]" in full_text or "[WAIT_FOR_USER_INPUT]" in full_text
        owner_input_match = re.search(r'\[OWNER_INPUT_NEEDED,\s*reason="([^"]+)"(?:,\s*summary="([^"]+)")?\]', full_text)
        convo_ended_match = re.search(r'\[CONVERSATION_ENDED,\s*summary="([^"]+)"\]', full_text)
        tool_match = re.search(r'\[TOOL_ACCESS_NEEDED,\s*tool="([^"]+)",\s*query="([^"]+)"\]', full_text)
        image_matches = re.findall(r'\[IMAGE,\s*([^\]]+)\]', full_text)
        
        reply_text = full_text
        reply_text = re.sub(r'\[OWNER_INPUT_NEEDED,.*?\]', '', reply_text)
        reply_text = re.sub(r'\[CONVERSATION_ENDED,.*?\]', '', reply_text)
        reply_text = re.sub(r'\[TOOL_ACCESS_NEEDED,.*?\]', '', reply_text)
        reply_text = re.sub(r'\[IMAGE,.*?\]', '', reply_text)
        reply_text = reply_text.replace("[WAIT_FOR_TARGET_REPLY]", "").replace("[WAIT_FOR_USER_INPUT]", "").strip()

        return {
            "text": reply_text,
            "is_waiting": waiting_match,
            "owner_input_needed": owner_input_match.group(1) if owner_input_match else None,
            "summary": (convo_ended_match.group(1) if convo_ended_match else 
                        owner_input_match.group(2) if (owner_input_match and owner_input_match.lastindex >= 2) else None),
            "conversation_ended": convo_ended_match is not None,
            "tool_needed": {"tool": tool_match.group(1), "query": tool_match.group(2)} if tool_match else None,
            "images": [img.strip() for img in image_matches]
        }

    async def execute_hermes_tool(self, tool_name: str, query: str) -> str:
        toolset_map = {
            "google_drive": "google-workspace",
            "drive": "google-workspace",
            "gmail": "google-workspace",
            "calendar": "google-workspace",
            "web_search": "web",
            "browser": "browser",
            "terminal": "terminal",
            "vision_analyze": "vision",
            "read_file": "file"
        }
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
        """檢查是否連續發送超過 N 則訊息 (只計發給使用者的訊息)"""
        count = 0
        for m in reversed(msgs):
            if m.get("sender") != "Hermes":
                break
            
            text = m.get("text", "").strip()
            # 僅計算發送給使用者的內容 (排除技術性/不可見的動作日誌)
            if not (text.startswith("[系統") or text.startswith("[TOOL")):
                count += 1
        
        if count >= self.state["spam_limit"]:
            error_msg = f"[OWNER_INPUT_NEEDED] SECURITY_PROTOCOL_ACTIVATED: Spam limit reached ({self.state['spam_limit']}). Your current task loop MUST TERMINATE IMMEDIATELY. Do NOT attempt to use alternative tools (like execute_code) or modify message headers to bypass this safety limit. Report the status to the Owner and WAIT."
            self.history.write_log(f"ERROR: {error_msg}")
            raise Exception(error_msg)

    async def generate_and_send_reply(self, msgs: List[Dict[str, Any]]) -> None:
        """核心回覆邏輯：生成 AI 回應並處理工具調用"""
        max_turns = 3  # 限制單次回覆循環內的工具調用次數，防止無限遞迴
        current_turn = 0
        
        while current_turn < max_turns:
            try:
                context_lines = self.history.get_full_context(msgs, self.state["sent_messages"])
                prompt = self._build_prompt(msgs, context_lines)
                
                response = self.client.models.generate_content(model=self.model_name, contents=prompt)
                result = self._parse_response(str(getattr(response, 'text', '')).strip())
                
                # 處理文字訊息
                text_to_send = result["text"]
                if not text_to_send and result.get("images"):
                    text_to_send = "傳送圖片如下："

                if text_to_send and text_to_send not in self.state["sent_messages"]:
                    # 在真正發送前檢查 Spam Limit
                    try:
                        self._check_spamming(msgs)
                    except Exception as e:
                        self.state["final_report"] = str(e)
                        raise e

                    await self.channel.send_message(text_to_send)
                    self.history.write_log(f"SENT: {text_to_send}")
                    self.state["sent_messages"].append(text_to_send.strip())
                
                # 處理圖片發送
                for img_path in result.get("images", []):
                    await self.channel.send_image(img_path)
                    self.history.write_log(f"SENT IMAGE: {img_path}")
                    self.state["sent_messages"].append(f"[IMAGE: {img_path}]")
                
                # 更新最後處理狀態
                latest_msgs = await self.channel.extract_messages()
                if latest_msgs:
                    self.state["last_processed_msg"] = latest_msgs[-1].get("text", "")
                
                if result["summary"]:
                    summary_report = f"\n[REPORT]\n{result['summary']}\n[/REPORT]"
                    self.history.write_log(f"--- TASK SUMMARY ---\n{result['summary']}\n--------------------")
                    print(summary_report)

                # 判定後續行為
                if result["is_waiting"]:
                    self.history.write_log("DEBUG: [WAIT_FOR_USER_INPUT] detected. Waiting for store response.")
                    break  # 跳出循環，等待外部輪詢
                
                if result["owner_input_needed"]:
                    self.state.update({
                        "exit_at": time.time() + OWNER_INPUT_WAIT,
                        "final_report": f"[OWNER_INPUT_NEEDED] {result['owner_input_needed']}"
                    })
                    break
                
                if result["conversation_ended"]:
                    self.state.update({
                        "exit_at": time.time() + CONVERSATION_END_WAIT,
                        "final_report": f"[CONVERSATION_ENDED] {result['summary'] or 'Mission complete.'}"
                    })
                    break
                
                if result["tool_needed"]:
                    tool_name = result["tool_needed"]["tool"]
                    query = result["tool_needed"]["query"]
                    self.history.write_log(f"TOOL_START: {tool_name} with query: {query}")
                    
                    try:
                        if tool_name == "image_gen":
                            tool_output = await self._generate_image_locally(query)
                        else:
                            tool_output = await self.execute_hermes_tool(tool_name, query)
                            
                        self.state["sent_messages"].append(f"[系統通知] 工具執行成功。結果為: {tool_output}")
                        # 工具執行完後，將 current_turn + 1 並繼續循環（讓 AI 看到工具結果）
                        current_turn += 1
                        msgs = await self.channel.extract_messages()
                        continue 
                    except Exception as e:
                        self.history.write_log(f"TOOL_ERROR: {tool_name} failed: {str(e)}")
                        break
                
                break # 無工具需求也無特定狀態，正常結束
                
            except Exception as e:
                if "[OWNER_INPUT_NEEDED] SECURITY_PROTOCOL_ACTIVATED" in str(e):
                    raise e
                self.history.write_log(f"Error in generate_and_send_reply: {e}")
                self.state["final_report"] = f"Error in generate_and_send_reply: {str(e)}"
                break

    async def run(self) -> Optional[str]:
        start_time = time.time()
        self.history.write_log(f"Proxy Engine started for {self.target_chat} (ID: {self.target_chat_id}) [PID: {os.getpid()}]")
        await self.channel.bring_to_front()
        selection = await self.channel.select_chat(self.target_chat, self.target_chat_id)
        if selection.get("status") != "success":
            error_msg = f"Failed to select chat '{self.target_chat}': {selection.get('error', 'Unknown error')}"
            self.history.write_log(error_msg)
            return error_msg
        
        msgs = await self.channel.extract_messages()
        if msgs is None: return

        context_lines = self.history.get_full_context(msgs, [])
        await self.analyze_context(context_lines)

        self.state.update(self.history.rebuild_state(msgs or [], self.task_description))
        
        try:
            # 始終允許啟動時進行一次評估，由 AI 根據上下文決定是 [WAIT] 還是繼續行動
            await self.generate_and_send_reply(msgs or [])
        except Exception:
            # generate_and_send_reply sets final_report on exception
            return self.state.get("final_report")
        except Exception:
            # generate_and_send_reply sets final_report on exception
            return self.state.get("final_report")

        while True:
            if time.time() - start_time > RUNTIME_TIMEOUT:
                msg = "[SILENT_RESTART_NEEDED] 任務運行已達 50 分鐘上限。請代理人『直接再次啟動』相同的背景任務指令，嚴禁發送任何文字訊息給 User 或 Owner，保持完全靜默。"
                self.state["final_report"] = msg
                self.history.write_log(msg)
                break
            if self.state.get("exit_at") and time.time() >= self.state["exit_at"]:
                break
            try:
                msgs = await self.channel.extract_messages()
                if msgs:
                    latest = msgs[-1]
                    is_hermes = latest.get("sender") in ["Hermes", OWNER_NAME]
                    is_new = latest["text"].strip() != self.state.get("last_processed_msg", "").strip()
                    if not is_hermes and is_new:
                        if self.state.get("exit_at"): self.state["exit_at"] = None
                        await self.generate_and_send_reply(msgs)
            except Exception as e:
                error_msg = f"Critical error in message polling: {e}"
                self.history.write_log(error_msg)
                self.state["final_report"] = error_msg
                break
            await asyncio.sleep(POLL_INTERVAL)

        self.history.write_log("Session concluded.")
        return self.state.get("final_report")
