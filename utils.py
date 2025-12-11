from typing import Optional, Dict, Any, List
import json

def parse_sse_json(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Given an SSE response like:
        event: message
        id: ...
        data: {...JSON...}

    extract and return the JSON object from the first 'data: ' line.
    """
    for line in response_text.splitlines():
        if line.startswith("data: "):
            data = line[6:]
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                print("Could not parse JSON from SSE data:", data)
                return None
    return None

def extract_text_from_content(content_items: List[Dict]) -> str:
    """Extract text from MCP content items"""
    text_parts = []
    for item in content_items:
        if item.get('type') == "text" and 'text' in item:
            text_parts.append(item['text'])
    return "\n".join(text_parts) if text_parts else json.dumps(content_items)