import asyncio
from ddgs import DDGS

def test_searches():
    queries = [
        '("Huawei Technologies (Malaysia) Sdn. Bhd.") AND ("Taiwan Semiconductor Manufacturing Company, Limited") AND (supplier OR supplies OR distributor OR partner OR vendor OR "available at" OR stocks)',
        '"Huawei Technologies" "Taiwan Semiconductor" supplier OR vendor OR partner',
        'Huawei TSMC supplier partner'
    ]
    with DDGS() as ddgs:
        for q in queries:
            print(f"\nQuery: {q}")
            results = list(ddgs.text(q, max_results=5))
            print(f"Results found: {len(results)}")
            for r in results[:2]:
                print(f" - {r.get('title')}")

test_searches()
