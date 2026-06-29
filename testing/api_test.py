"""
test_api.py
A simple standalone script to test the public OpenSanctions API.
Because OpenCorporates requires a lengthy API key approval process, we use 
OpenSanctions for prototyping. It requires NO API KEY, is 100% free for testing, 
and aggregates registration data from global registries (including OpenCorporates).
"""

import asyncio
import json
import httpx
import os
from pathlib import Path
from dotenv import load_dotenv

# Automatically locate and load the .env file from the parent directory
# This allows test_api.py to run from the Testing folder while using the main .env
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# =====================================================================
# TEST CONFIGURATION
# Modify these variables to test different companies.
# Note: Because this is a compliance database, major corporations 
# and financial institutions yield the best results.
# =====================================================================
TEST_COMPANY_NAME = "Maybank Berhad"         # e.g., "Grab", "Maybank", "AirAsia"
OPENSANCTIONS_API_KEY = os.getenv("OPENSANCTIONS_API_KEY")


async def test_registry_api(company_name: str):
    if not OPENSANCTIONS_API_KEY:
        print("❌ Please add your free OpenSanctions API key at the top of the script.")
        print("Get it instantly here: https://www.opensanctions.org/api/")
        return

    print("=" * 60)
    print(f"Initializing OpenSanctions API Search...")
    print(f"Querying Legal Entity: Name='{company_name}'")
    print("=" * 60)

    # OpenSanctions Match Endpoint
    url = "https://api.opensanctions.org/match/default"
    headers = {"Authorization": f"ApiKey {OPENSANCTIONS_API_KEY}"}
    
    # The API expects a specific JSON query schema for fuzzy matching
    payload = {
        "queries": {
            "test_query": {
                "schema": "LegalEntity",
                "properties": {
                    "name": [company_name]
                }
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Hitting the endpoint with auth headers
            response = await client.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                # Extract the matches for our specific 'test_query'
                results = data.get("responses", {}).get("test_query", {}).get("results", [])
                
                if not results:
                    print(f"⚠️ No matching legal entities found for '{company_name}'.")
                    return

                # Filter for decent matches (score > 0.5) to remove garbage hits
                valid_hits = [r for r in results if r.get("score", 0) > 0.5]
                print(f"Success! Found {len(valid_hits)} matching entity/entities:\n")
                
                for idx, match in enumerate(valid_hits):
                    props = match.get("properties", {})
                    
                    # Package the extracted data cleanly
                    parsed_result = {
                        "match_number": idx + 1,
                        "legal_name": match.get("caption"),
                        "match_score": match.get("score"),
                        
                        # --- LOCAL REGISTRATION ID EXTRACTION ---
                        # OpenSanctions aggregates UENs, SSMs, and LEIs here
                        "registration_number": props.get("registrationNumber", ["N/A"])[0],
                        "jurisdiction": props.get("jurisdiction", ["N/A"])[0],
                        "country": props.get("country", ["N/A"])[0],
                        # ----------------------------------------
                        
                        "incorporation_date": props.get("incorporationDate", ["N/A"])[0],
                        "entity_type": props.get("legalForm", ["N/A"])[0],
                        
                        # Show which watchlists/registries this data came from
                        "datasets_found_in": match.get("datasets", [])
                    }
                    print(json.dumps(parsed_result, indent=2))
                    print("-" * 40)
            else:
                print(f"❌ API Request Failed with Status Code: {response.status_code}")
                print(response.text)
                
    except Exception as e:
        print(f"❌ Connection Error occurred: {str(e)}")


if __name__ == "__main__":
    # Run the async test block
    asyncio.run(
        test_registry_api(
            company_name=TEST_COMPANY_NAME
        )
    )