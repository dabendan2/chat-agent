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
    """
    Verify that if a task is already started (history exists), 
    restarting the engine should NOT result in a duplicate message.
    """
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
        
        # Set side effect for two calls (Analyzer, then decision)
        mock_gen.side_effect = [
            MockResponse(json.dumps({
                "service_target": "friends",
                "task_start_time": "[1:00 AM]",
                "is_started": True
            })),
            MockResponse(previous_msg + " [WAIT_FOR_TARGET_REPLY]")
        ]

        engine = ChatEngine(mock_channel, chat_name, "詢問 5/17 時間空檔", api_key="test")
        
        # Patch the continuous loop to exit immediately for testing
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            try:
                await engine.run()
            except asyncio.CancelledError:
                pass

        # ASSERTION: No new message should have been sent because of idempotency check
        assert mock_channel.send_message.call_count == 0
        assert engine.state["is_started"] is True

@pytest.mark.asyncio
async def test_label_isolation_logic():
    """
    Verify that internal reporting content is NOT leaked into the public message.
    """
    mock_channel = AsyncMock()
    engine = ChatEngine(mock_channel, "test", "test task", api_key="test")
    
    # Standard Case
    raw_ai_output = "Hello! [OWNER_INPUT_NEEDED, reason=\"timed out\", summary=\"waiting 30m\"]"
    parsed = engine._parse_response(raw_ai_output)
    assert parsed["text"] == "Hello!"
    assert parsed["owner_input_needed"] == "timed out"
    
    # Leak Prevention Case (The '30 minutes monitor' bug)
    raw_leak_output = "The contact is read but no reply. [Hermes] tracked 30m. [WAIT_FOR_TARGET_REPLY]"
    parsed_leak = engine._parse_response(raw_leak_output)
    
    # GUIDANCE: The text should not contain internal state markers like [Hermes]
    # This test provides guidance that ANY bracketed content not recognized as a tool/tag
    # should be flagged or carefully handled.
    assert "[Hermes]" not in parsed_leak["text"]
    # We stripped the brackets, so "[Hermes]" is gone. 
    # "30m" might remain but the structure is sanitized.
    assert "[" not in parsed_leak["text"]

def test_output_format_strictness():
    """
    Test suite to enforce strict output formatting rules.
    This acts as a 'guidance' for what a valid response looks like.
    """
    engine = ChatEngine(MagicMock(), "test", "test task", api_key="test")
    
    valid_outputs = [
        "How are you? [WAIT_FOR_TARGET_REPLY]",
        "Setting appointment. [CONVERSATION_ENDED, summary=\"Done\"]",
        "Need help. [OWNER_INPUT_NEEDED, reason=\"Blocked\", summary=\"Help\"]",
        "Check this [IMAGE, /path/img.png] [WAIT_FOR_TARGET_REPLY]"
    ]
    
    invalid_outputs = [
        "No label at all",
        "Custom label [HEHERMES] is bad",
        "Double labels [WAIT_FOR_TARGET_REPLY] [CONVERSATION_ENDED, summary=\"x\"]",
        "Internal state leaked: Tracking for 30s... [WAIT_FOR_TARGET_REPLY]"
    ]
    
    for output in valid_outputs:
        parsed = engine._parse_response(output)
        # Text should be clean
        assert "[" not in parsed["text"]
        # Must have exactly one state identified (except for IMAGE which is additive)
        state_count = sum([parsed["is_waiting"], parsed["owner_input_needed"] is not None, parsed["conversation_ended"]])
        assert state_count == 1, f"Output '{output}' should have exactly one state label."

    for output in invalid_outputs:
        parsed = engine._parse_response(output)
        # If it has internal state or bad labels, these conditions should fail
        if "[" in parsed["text"]:
            # This is exactly what happened with the [Hermes] leak
            pytest.fail(f"GUIDANCE VIOLATION: Output '{output}' leaked internal brackets into public text: '{parsed['text']}'")
