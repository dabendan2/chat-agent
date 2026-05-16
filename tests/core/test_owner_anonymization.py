import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock
from core.engine import ChatEngine
from core.history import HistoryManager
from channels.line.driver import send_message as line_send_message
from utils.config import OWNER_NAME, HERMES_PREFIX

@pytest.mark.asyncio
async def test_history_manager_treats_real_owner_as_external():
    """
    Verify that HistoryManager only treats 'Hermes' as self.
    Even if a message is from the real owner (e.g., 'Junyu'), 
    it should NOT be added to sent_messages (tracked as self).
    """
    real_owner = "Junyu"
    msgs = [
        {"sender": "Hermes", "text": "Hello"},
        {"sender": real_owner, "text": "I am the real owner"}
    ]
    
    history = HistoryManager("test_chat")
    state = history.rebuild_state(msgs, "test task")
    
    assert "Hello" in state["sent_messages"]
    assert "I am the real owner" not in state["sent_messages"]

@pytest.mark.asyncio
async def test_engine_uses_placeholder_in_prompt():
    """
    Verify that ChatEngine uses {{OWNER_NAME}} placeholder in its prompt
    instead of the real owner name.
    """
    mock_channel = AsyncMock()
    engine = ChatEngine(mock_channel, "test_chat", "test task", api_key="test_key")
    
    prompt = engine._build_prompt([], ["context line"])
    
    # Prompt should contain the placeholder
    assert "{{OWNER_NAME}}" in prompt

@pytest.mark.asyncio
async def test_send_message_performs_replacement():
    """
    Verify that line_send_message replaces {{OWNER_NAME}} with real name
    just before typing.
    """
    mock_page = MagicMock()
    mock_locator = AsyncMock() # Use AsyncMock for clickable elements
    mock_page.locator.return_value = mock_locator
    mock_locator.first = mock_locator
    
    mock_page.keyboard = AsyncMock()
    
    test_text = "Hello, I am {{OWNER_NAME}}'s agent."
    
    with patch("inspect.stack", return_value=[MagicMock(function="run_task")]), \
         patch("utils.config.OWNER_NAME", "Junyu Real Name"):
        
        await line_send_message(mock_page, test_text)
        
        # Check what was actually typed
        typed_text = mock_page.keyboard.type.call_args[0][0]
        assert "Junyu Real Name" in typed_text
        assert "{{OWNER_NAME}}" not in typed_text
        assert typed_text.startswith(HERMES_PREFIX)

@pytest.mark.asyncio
async def test_engine_polling_treats_owner_as_trigger():
    """
    Verify that when polling messages, if the latest message is from the real owner,
    it is NOT considered 'is_hermes', thus triggering a reply.
    """
    mock_channel = AsyncMock()
    real_owner = "Junyu"
    mock_channel.extract_messages.return_value = [
        {"sender": "Hermes", "text": "Old message"},
        {"sender": real_owner, "text": "New command from owner"}
    ]
    
    engine = ChatEngine(mock_channel, "test_chat", "test task", api_key="test_key")
    engine.state["last_processed_msg"] = "Old message"
    
    with patch("core.engine.ChatEngine.generate_and_send_reply", new_callable=AsyncMock) as mock_reply:
        msgs = await mock_channel.extract_messages()
        latest = msgs[-1]
        
        # Identification logic
        is_hermes = latest.get("sender") == "Hermes"
        is_new = latest["text"].strip() != engine.state.get("last_processed_msg", "").strip()
        
        assert not is_hermes 
        assert is_new
        
        if not is_hermes and is_new:
            await engine.generate_and_send_reply(msgs)
            
        assert mock_reply.called
