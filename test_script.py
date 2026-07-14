import json
from unittest.mock import MagicMock, AsyncMock

try:
    print(json.loads(MagicMock()))
except Exception as e:
    print("MagicMock error:", type(e), e)

try:
    m = AsyncMock()
    m.return_value = "NOT_JSON"
    print(json.loads(m))
except Exception as e:
    print("AsyncMock error:", type(e), e)
