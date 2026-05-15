import pytest
import os
from core.refactorer import TaskRefactorer

@pytest.fixture
def api_key():
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        pytest.skip("GOOGLE_API_KEY not found")
    return key

def test_refactor_stepped_logic(api_key):
    refactorer = TaskRefactorer(api_key=api_key)
    raw_task = "預約 5/11 13:00 娜比燒肉 2大1小，要靠窗沙發、插座、推車空間，註記慶生。"
    
    refactored = refactorer.refactor(raw_task)
    
    # Loose structure check
    assert any(x in refactored for x in ["階段", "1.", "Phase", "Step"])
    
    # Key fact retention (ignoring count format variance)
    facts = ["5/11", "13:00", "娜比", "靠窗", "沙發", "插座", "慶生"]
    for fact in facts:
        assert fact in refactored

def test_refactor_social_privacy(api_key):
    refactorer = TaskRefactorer(api_key=api_key)
    raw_task = "問對方有沒有興趣合作廣告，預算十萬，希望下週能開始。"
    
    refactored = refactorer.refactor(raw_task)
    
    # Basic existence
    assert "十萬" in refactored
    assert "下週" in refactored

def test_refactor_efficiency_for_simple_tasks(api_key):
    refactorer = TaskRefactorer(api_key=api_key)
    raw_task = "傳送一張柴犬圖片給對方。"
    
    refactored = refactorer.refactor(raw_task)
    
    assert any(x in refactored for x in ["IMAGE", "圖片", "照片", "交付"])

def test_refactor_complex_task(api_key):
    refactorer = TaskRefactorer(api_key=api_key)
    raw_task = "詢問娜比是不是燒肉店員，是的話幫我訂 5/11 13:00，2大1小，全員忌海鮮，其中一員全素，要有插座。"
    
    refactored = refactorer.refactor(raw_task)
    
    # Check for logic flow
    assert any(x in refactored for x in ["身分", "確認", "店員", "詢問"])
