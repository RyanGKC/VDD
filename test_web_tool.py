import asyncio
from custom_tools.web_tool import ddg_search, web_search_and_read

async def test():
    print("Testing ddg_search...")
    res = await ddg_search("Weather in Malaysia", 3)
    print("ddg_search result:", res)
    
    print("\nTesting web_search_and_read...")
    pages = await web_search_and_read("Weather in Malaysia", 3)
    print("web_search_and_read result:", pages)

asyncio.run(test())
