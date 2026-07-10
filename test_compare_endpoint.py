import asyncio
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

def test_compare_endpoint():
    # Test AAPL
    response = client.get("/api/compare_financials?company_name=AAPL")
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print("Keys in response:", data.keys())
    print("yfinance status:", data["yfinance"]["status"])
    print("fmp status:", data["fmp"]["status"])
    
if __name__ == "__main__":
    test_compare_endpoint()
