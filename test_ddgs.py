from duckduckgo_search import DDGS
import json

with DDGS() as ddgs:
    print(json.dumps(list(ddgs.text("Weather in Malaysia", max_results=3, backend="lite")), indent=2))
    
    print("Trying default backend...")
    print(json.dumps(list(ddgs.text("Weather in Malaysia", max_results=3)), indent=2))
    
    print("Trying html backend...")
    print(json.dumps(list(ddgs.text("Weather in Malaysia", max_results=3, backend="html")), indent=2))
