#!/usr/bin/env python3
"""
WebSocket Test Script for Railway Deployment

This script tests the Application WebSocket connectivity on your Railway deployment.
It will authenticate, connect to WebSocket, and test various message types.
"""

import asyncio
import json
import sys
from datetime import datetime
from typing import Optional

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosedError, WebSocketException


class WebSocketTester:
    def __init__(self, base_url: str = "https://atomik-backend-development.up.railway.app"):
        self.base_url = base_url.rstrip('/')
        self.ws_url = base_url.replace('https://', 'wss://').replace('http://', 'ws://')
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        
    async def authenticate(self, email: str, password: str) -> bool:
        """Authenticate and get JWT token"""
        print(f"🔐 Authenticating as {email}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                auth_data = {
                    "username": email,  # FastAPI OAuth2PasswordRequestForm uses 'username'
                    "password": password
                }
                
                async with session.post(
                    f"{self.base_url}/api/v1/auth/login",
                    data=auth_data  # Send as form data
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.token = data.get("access_token")
                        
                        if not self.token:
                            print("❌ No access token in response")
                            return False
                        
                        print("✅ Authentication successful!")
                        
                        # Get user info
                        await self.get_user_info()
                        return True
                    else:
                        error_text = await response.text()
                        print(f"❌ Authentication failed: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False
    
    async def get_user_info(self) -> bool:
        """Get current user info to extract user_id"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.token}"}
                
                async with session.get(
                    f"{self.base_url}/api/v1/auth/verify/",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        user_data = data.get("user", {})
                        self.user_id = str(user_data.get("id"))
                        print(f"👤 User ID: {self.user_id}")
                        print(f"📧 Email: {user_data.get('email')}")
                        print(f"👥 Username: {user_data.get('username')}")
                        return True
                    else:
                        error_text = await response.text()
                        print(f"❌ Failed to get user info: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            print(f"❌ Error getting user info: {e}")
            return False
    
    async def test_http_stats(self) -> bool:
        """Test the HTTP stats endpoint"""
        print("\n📊 Testing HTTP WebSocket stats endpoint...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/v1/chat/ws/stats") as response:
                    if response.status == 200:
                        data = await response.json()
                        print("✅ Stats endpoint working:")
                        print(f"   - Active connections: {data.get('data', {}).get('total_connections', 0)}")
                        print(f"   - Total channels: {data.get('data', {}).get('total_channels', 0)}")
                        return True
                    else:
                        print(f"❌ Stats endpoint failed: {response.status}")
                        return False
                        
        except Exception as e:
            print(f"❌ Error testing stats endpoint: {e}")
            return False
    
    async def connect_websocket(self) -> bool:
        """Connect to the WebSocket endpoint"""
        if not self.token or not self.user_id:
            print("❌ Must authenticate first")
            return False
        
        ws_endpoint = f"{self.ws_url}/api/v1/chat/ws/{self.user_id}?token={self.token}"
        print(f"\n🔗 Connecting to WebSocket: {ws_endpoint}")
        
        try:
            self.websocket = await websockets.connect(
                ws_endpoint,
                timeout=10,
                ping_interval=20,
                ping_timeout=10
            )
            print("✅ WebSocket connected successfully!")
            return True
            
        except Exception as e:
            print(f"❌ WebSocket connection failed: {e}")
            return False
    
    async def listen_for_messages(self):
        """Listen for incoming WebSocket messages"""
        if not self.websocket:
            return
        
        print("👂 Listening for messages...")
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "unknown")
                    timestamp = data.get("timestamp", "")
                    
                    print(f"📨 Received [{msg_type}]: {data}")
                    
                except json.JSONDecodeError:
                    print(f"📨 Received (raw): {message}")
                    
        except ConnectionClosedError as e:
            print(f"🔌 WebSocket connection closed: {e}")
        except Exception as e:
            print(f"❌ Error listening for messages: {e}")
    
    async def send_test_messages(self):
        """Send various test messages"""
        if not self.websocket:
            print("❌ No WebSocket connection")
            return
        
        print("\n📤 Sending test messages...")
        
        test_messages = [
            {
                "type": "ping",
                "timestamp": datetime.utcnow().isoformat()
            },
            {
                "type": "subscribe_channel",
                "channel_id": "general"
            },
            {
                "type": "send_message",
                "channel_id": "general",
                "content": "Hello from WebSocket test script! 🚀"
            },
            {
                "type": "typing",
                "channel_id": "general"
            }
        ]
        
        for i, message in enumerate(test_messages, 1):
            try:
                await self.websocket.send(json.dumps(message))
                print(f"✅ Sent message {i}/{len(test_messages)}: {message['type']}")
                await asyncio.sleep(1)  # Small delay between messages
                
            except Exception as e:
                print(f"❌ Failed to send message {i}: {e}")
    
    async def disconnect(self):
        """Close WebSocket connection"""
        if self.websocket:
            await self.websocket.close()
            print("🔌 WebSocket disconnected")
    
    async def run_full_test(self, email: str, password: str):
        """Run the complete test suite"""
        print("🧪 Starting WebSocket Test Suite")
        print("=" * 50)
        
        # Step 1: Test HTTP stats endpoint
        await self.test_http_stats()
        
        # Step 2: Authenticate
        if not await self.authenticate(email, password):
            print("❌ Test failed: Authentication required")
            return False
        
        # Step 3: Connect WebSocket
        if not await self.connect_websocket():
            print("❌ Test failed: WebSocket connection required")
            return False
        
        # Step 4: Start listening task
        listen_task = asyncio.create_task(self.listen_for_messages())
        
        # Step 5: Send test messages
        await asyncio.sleep(1)  # Let connection establish
        await self.send_test_messages()
        
        # Step 6: Wait for responses
        print("\n⏳ Waiting for responses (10 seconds)...")
        await asyncio.sleep(10)
        
        # Step 7: Cleanup
        listen_task.cancel()
        await self.disconnect()
        
        print("\n✅ Test completed!")
        return True


async def main():
    """Main test function"""
    print("WebSocket Test Script for Railway Deployment")
    print("=" * 50)
    
    # Default test credentials - modify these as needed
    email = "test@atomiktrading.com"
    password = "Test123!"
    
    # Allow command line override
    if len(sys.argv) >= 3:
        email = sys.argv[1]
        password = sys.argv[2]
        print(f"Using command line credentials: {email}")
    else:
        print(f"Using default test credentials: {email}")
        print("(You can pass custom credentials: python test_websocket.py email@example.com password)")
    
    # Optionally change the base URL for different environments
    base_url = "https://atomik-backend-development.up.railway.app"
    
    tester = WebSocketTester(base_url)
    
    try:
        await tester.run_full_test(email, password)
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted by user")
        await tester.disconnect()
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        await tester.disconnect()


if __name__ == "__main__":
    # Install required packages: pip install aiohttp websockets
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Script error: {e}")
        sys.exit(1)