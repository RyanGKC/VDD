import asyncio
import httpx

async def test():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": "DeepMind Project Astra"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"}
        )
        print("Status:", resp.status_code)
        print("Text preview:", resp.text[:1000])

asyncio.run(test())
