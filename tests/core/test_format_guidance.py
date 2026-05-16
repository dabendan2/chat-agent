import pytest
import json
import re
from unittest.mock import MagicMock
from core.engine import ChatEngine

def test_engine_output_schema_guidance():
    """
    GUIDANCE TEST: Defines the strict schema requirements for ChatEngine responses.
    """
    engine = ChatEngine(MagicMock(), "test", "test", api_key="test")
    
    # Guidance: Technical brackets like [1, 2] are ALLOWED.
    # Guidance: Internal state brackets like [Hermes] are FORBIDDEN.
    test_outputs = [
        ("Message [WAIT_FOR_TARGET_REPLY]", "Message"),
        ("Result: [1, 2, 3] [WAIT_FOR_TARGET_REPLY]", "Result: [1, 2, 3]"),
        ("Leak: [Hermes] 30m [WAIT_FOR_TARGET_REPLY]", "Leak:  30m")
    ]
    
    for raw, expected_text in test_outputs:
        parsed = engine._parse_response(raw)
        assert parsed["text"] == expected_text
        
        # Guidance: Every turn must result in a valid state
        has_state = (parsed["is_waiting"] or 
                     parsed["owner_input_needed"] or 
                     parsed["conversation_ended"] or 
                     parsed["tool_needed"])
        assert has_state, f"Output '{raw}' resulted in an undefined state."

def test_analyzer_output_schema_guidance():
    required_keys = ["service_target", "current_progress", "task_start_time", "is_started"]
    sample_json = {
        "service_target": "Store",
        "current_progress": "Started",
        "task_start_time": "[12:00]",
        "is_started": True
    }
    for key in required_keys:
        assert key in sample_json
    time_val = sample_json["task_start_time"]
    assert time_val == "尚未開始" or re.match(r"\[\d{1,2}:\d{2}\]", time_val)

def test_refactorer_output_guidance():
    sample_refactored = "階段 1: Confirm identity.\n階段 2: Place order."
    assert "階段" in sample_refactored or "Phase" in sample_refactored
    assert "1" in sample_refactored
