import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.abspath("src"))
from core.engine import ChatEngine
from utils.config import HERMES_PREFIX

@pytest.mark.asyncio
async def test_spam_control_with_chain_break_fix():
    """
    Verify that spam control correctly identifies Hermes messages even if the prefix was missing in history
    (Wait, actually, after my patch, the prefix should NEVER be missing in history for Hermes messages).
    
    This test verifies that if we have 3 consecutive Hermes messages, it blocks the 4th.
    """
    mock_channel = AsyncMock()
    # Mock 3 consecutive visible messages from Hermes
    # After my patches, the driver should reliably label these as "Hermes"
    history = [
        {"sender": "Hermes", "text": "Msg 1"},
        {"sender": "Hermes", "text": "Msg 2"},
        {"sender": "Hermes", "text": "Msg 3"},
    ]
    
    engine = ChatEngine(mock_channel, "test_chat", "test_task", api_key="test_key")
    
    with patch("google.genai.Client"), \
         patch("core.engine.ChatEngine._build_prompt", return_value="test prompt"), \
         patch("os.path.exists", return_value=False): # Bypass physical log check
        
        engine.client.models.generate_content = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello world"
        engine.client.models.generate_content.return_value = mock_response
        
        # Should raise exception
        with pytest.raises(Exception, match=r"\[OWNER_INPUT_NEEDED\].*SECURITY_PROTOCOL_ACTIVATED"):
            await engine.generate_and_send_reply(history)

@pytest.mark.asyncio
async def test_engine_forces_prefix_on_ai_output():
    """
    Verify that the engine forces the prefix even if AI output doesn't have it.
    """
    mock_channel = AsyncMock()
    engine = ChatEngine(mock_channel, "test_chat", "test_task", api_key="test_key")
    
    with patch("google.genai.Client"), \
         patch("core.engine.ChatEngine._build_prompt", return_value="test prompt"), \
         patch("os.path.exists", return_value=False): # Bypass physical log check
        
        engine.client.models.generate_content = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "No prefix here" # AI forgets prefix
        engine.client.models.generate_content.return_value = mock_response
        
        await engine.generate_and_send_reply([])
        
        # Check if the prefix was added when sending
        sent_text = mock_channel.send_message.call_args[0][0]
        assert sent_text.startswith(HERMES_PREFIX)
        assert "No prefix here" in sent_text
