import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# Ensure the src directory is in the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from channels.line import driver as line_utils

@pytest.mark.asyncio
async def test_extract_messages_fails_when_container_missing():
    """
    TDD: Verify that extract_messages raises an exception when the chatroom container is missing.
    This prevents silent failures where an empty list is returned instead of an error.
    """
    mock_page = MagicMock()
    # Mocking the first evaluate call (scroll)
    mock_page.evaluate = AsyncMock()
    # Mocking the second evaluate call (extraction) to raise error
    mock_page.evaluate.side_effect = [None, Exception("JS Error: Error: Chatroom container not found")]
    
    with pytest.raises(Exception) as excinfo:
        await line_utils.extract_messages(mock_page, "Owner", "Chat")
    
    assert "Chatroom container not found" in str(excinfo.value)

@pytest.mark.asyncio
async def test_extract_messages_returns_empty_list_when_no_messages():
    """
    Verify that extract_messages returns an empty list when the container exists but has no message items.
    """
    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock()
    # First call: scroll (None), Second call: extraction ([])
    mock_page.evaluate.side_effect = [None, []]
    
    result = await line_utils.extract_messages(mock_page, "Owner", "Chat")
    
    assert isinstance(result, list)
    assert len(result) == 0

@pytest.mark.asyncio
async def test_extract_messages_date_awareness():
    """
    Verify that extract_messages correctly captures date headers and associates them with messages.
    """
    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock()
    
    # Mock data as it would come from the refined JS script
    mock_data = [
        {"sender": "Wayne", "text": "Old message", "timestamp": "10:00", "date": "May 12(Tue)"},
        {"sender": "Hermes", "text": "New message", "timestamp": "10:01", "date": "Yesterday"}
    ]
    
    mock_page.evaluate.side_effect = [None, mock_data]
    
    result = await line_utils.extract_messages(mock_page, "Owner", "Chat")
    
    assert len(result) == 2
    assert result[0]["date"] == "May 12(Tue)"
    assert result[1]["date"] == "Yesterday"

@pytest.mark.asyncio
async def test_extract_messages_chronological_order():
    """
    Verify that extract_messages returns messages in chronological order (Oldest -> Newest).
    The JS script now reverses the DOM order (which is Newest -> Oldest).
    """
    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock()
    
    # The JS script returns the reversed list
    mock_data = [
        {"sender": "Wayne", "text": "First", "timestamp": "08:00", "date": "Today"},
        {"sender": "Wayne", "text": "Second", "timestamp": "08:05", "date": "Today"}
    ]
    
    mock_page.evaluate.side_effect = [None, mock_data]
    
    result = await line_utils.extract_messages(mock_page, "Owner", "Chat")
    
    # In the final list, the first item should be the older one
    assert result[0]["text"] == "First"
    assert result[-1]["text"] == "Second"

@pytest.mark.asyncio
async def test_js_order_logic_fix():
    """
    Verify the JS string in line_utils correctly handles the LINE Extension DOM 
    quirk: Newest messages appear first in DOM traversal.
    We require results.reverse() to convert to Oldest First for the engine.
    """
    # Read the JS string from driver.py
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../src/channels/line/driver.py")
    with open(src_path, "r") as f:
        content = f.read()
    
    assert "results.reverse()" in content

@pytest.mark.asyncio
async def test_self_detection_logic():
    """
    Verify the self-detection logic uses data-direction='reverse', 
    which is the most reliable indicator in the current LINE Extension DOM.
    """
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../src/channels/line/driver.py")
    with open(src_path, "r") as f:
        content = f.read()
        
    assert "el.getAttribute('data-direction')" in content
    assert "direction === 'reverse'" in content

@pytest.mark.asyncio
async def test_timestamp_inheritance_logic():
    """
    Verify the JS string contains the logic to inherit timestamps 
    for clustered messages from the same sender.
    """
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../src/channels/line/driver.py")
    with open(src_path, "r") as f:
        content = f.read()
        
    assert "TIME INHERITANCE" in content
    assert "chronMessages[i].timestamp = chronMessages[i+1].timestamp" in content
    assert "chronMessages[i].sender === chronMessages[i+1].sender" in content
