import pytest
import os
from unittest.mock import patch
from packages.clips.transcription.diarizer import SpeakerDiarizer

def test_speaker_diarizer_availability():
    # 1. No token provided
    with patch.dict(os.environ, clear=True):
        diarizer = SpeakerDiarizer(hf_token=None)
        assert diarizer.is_available == False
        
        with pytest.raises(RuntimeError) as excinfo:
            diarizer._load_pipeline()
        assert "HuggingFace token required" in str(excinfo.value)
        
    # 2. Token provided via arg
    diarizer2 = SpeakerDiarizer(hf_token="fake_token")
    assert diarizer2.hf_token == "fake_token"

def test_speaker_diarizer_env_var():
    with patch.dict(os.environ, {"HF_TOKEN": "env_fake_token"}):
        diarizer = SpeakerDiarizer()
        assert diarizer.hf_token == "env_fake_token"
