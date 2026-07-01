import asyncio
from core.gemini_client import GeminiClient
from pydantic import BaseModel

class Dummy(BaseModel):
    hello: str

async def main():
    print("Initializing client...")
    client = GeminiClient()
    print("Calling generate_structured...")
    try:
        result = await client.generate_structured(
            system_instruction="You are a helpful assistant.",
            prompt="Say hello world in JSON.",
            schema=Dummy
        )
        print("Success:", result)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
