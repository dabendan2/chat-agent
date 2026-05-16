import pytest
import os
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from core.engine import ChatEngine
from core.history import HistoryManager

class MockResponse:
    def __init__(self, text):
        self.text = text

@pytest.mark.asyncio
async def test_engine_idempotency_on_restart(tmp_path):
    chat_name = "idempotency_test"
    log_file = tmp_path / f"{chat_name}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    previous_msg = "請問大家 5/17 是否有空？"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"[2026-05-16 01:00:00] SENT: {previous_msg}\n")

    mock_channel = AsyncMock()
    mock_channel.extract_messages.return_value = [
        {"sender": "Hermes", "text": previous_msg, "timestamp": "1:00 AM"}
    ]
    mock_channel.select_chat.return_value = {"status": "success"}

    with patch("core.history.LOG_DIR", tmp_path), \
         patch("google.genai.Client") as mock_client:
        
        mock_gen = mock_client.return_value.models.generate_content
        mock_gen.side_effect = [
            MockResponse(json.dumps({
                "service_target": "friends",
                "task_start_time": "[1:00 AM]",
                "is_started": True
            })),
            MockResponse(previous_msg + " [WAIT_FOR_TARGET_REPLY]")
        ]

        engine = ChatEngine(mock_channel, chat_name, "詢問 5/17 時間空檔", api_key="test")
        
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            try:
                await engine.run()
            except asyncio.CancelledError:
                pass

        assert mock_channel.send_message.call_count == 0
        assert engine.state["is_started"] is True
