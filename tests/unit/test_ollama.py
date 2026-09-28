import pytest
from unittest.mock import patch, MagicMock
from contextvault.llm.ollama_client import OllamaClient
from contextvault.llm.schemas import IntentClassification, FileClassification

def test_ollama_client_model_resolution():
    client = OllamaClient(model="lfm2.5")
    
    
    with patch.object(client, "list_models", return_value=["LiquidAI/lfm2.5-1.2b-instruct:latest", "gemma3:1b"]):
        resolved = client.model
        assert resolved == "LiquidAI/lfm2.5-1.2b-instruct:latest"

def test_ollama_client_json_extraction():
    client = OllamaClient()
    
    raw_markdown = """Here is the JSON you requested:
```json
{
  "intent": "search",
  "confidence": 0.95,
  "parameters": {"query": "cpu scheduling"}
}
```
Hope this helps!"""

    clean = client._extract_json_string(raw_markdown)
    parsed = IntentClassification.model_validate_json(clean)
    assert parsed.intent == "search"
    assert parsed.parameters["query"] == "cpu scheduling"

def test_ollama_client_schema_flexibility():
    
    data = '{"intent": "generate", "confidence": 0.9, "parameters": "memory management"}'
    parsed = IntentClassification.model_validate_json(data)
    assert parsed.intent == "generate"
    assert parsed.parameters == {"query": "memory management"}
