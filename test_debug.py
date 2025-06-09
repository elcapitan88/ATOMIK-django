#!/usr/bin/env python3
"""
Debug test to see what's happening with webhook responses
"""

import asyncio
import aiohttp
import json
from datetime import datetime

# Configuration
TARGET_URL = "https://api.atomiktrading.io"
WEBHOOK_TOKEN = "Uva9KWM-i_fvwT4Bsyqwn4GNmUwCXCuUO1MRy4t9oAw"
WEBHOOK_SECRET = "1153bd34c107ff34edca215dcc12ebb00b3bb07ac0ffe22fca4df60df277034a"

async def test_single_webhook():
    """Send one webhook and see full response"""
    
    webhook_url = f"{TARGET_URL}/api/v1/webhooks/{WEBHOOK_TOKEN}?secret={WEBHOOK_SECRET}"
    
    test_payload = {
        "action": "BUY",
        "symbol": "AAPL",
        "quantity": 100,
        "timestamp": datetime.now().isoformat(),
        "source": "debug_test"
    }
    
    print(f"🔍 DEBUG TEST")
    print(f"URL: {webhook_url}")
    print(f"Payload: {json.dumps(test_payload, indent=2)}")
    print("=" * 60)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=test_payload) as response:
                response_text = await response.text()
                
                print(f"Status Code: {response.status}")
                print(f"Headers: {dict(response.headers)}")
                print(f"Response Body (raw): {response_text}")
                
                try:
                    response_data = json.loads(response_text)
                    print(f"\nResponse Body (parsed):")
                    print(json.dumps(response_data, indent=2))
                    
                    print(f"\nKey Fields:")
                    print(f"- railway_optimized: {response_data.get('railway_optimized', 'NOT FOUND')}")
                    print(f"- processing_time_ms: {response_data.get('processing_time_ms', 'NOT FOUND')}")
                    print(f"- status: {response_data.get('status', 'NOT FOUND')}")
                    print(f"- message: {response_data.get('message', 'NOT FOUND')}")
                    
                except json.JSONDecodeError:
                    print("Failed to parse response as JSON")
                    
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_single_webhook())