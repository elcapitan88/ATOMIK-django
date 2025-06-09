#!/usr/bin/env python3
"""
Webhook Stress Testing Suite
Tests high-frequency trading scenarios and memory stability
"""

import asyncio
import aiohttp
import time
import json
import statistics
import psutil
import os
from datetime import datetime
from typing import List, Dict, Any
import random
import hashlib
import hmac

# Configuration
BASE_URL = "https://api.atomiktrading.io"  # Production server URL
WEBHOOK_TOKEN = "Uva9KWM-i_fvwT4Bsyqwn4GNmUwCXCuUO1MRy4t9oAw"  # Production webhook token
WEBHOOK_SECRET = "1153bd34c107ff34edca215dcc12ebb00b3bb07ac0ffe22fca4df60df277034a"  # Production webhook secret

# Test scenarios
class StressTestScenarios:
    """Different stress test scenarios"""
    
    @staticmethod
    def high_frequency_trading():
        """Rapid buy/sell signals"""
        return [
            {"action": "BUY", "ticker": "MNQM5", "quantity": 2, "price": 100.50},
            {"action": "SELL", "ticker": "MNQM5", "quantity": 2, "price": 100.75},
        ]
    
    @staticmethod
    def burst_trading():
        """Burst of identical signals"""
        signal = {"action": "BUY", "ticker": "ESM5", "quantity": 1, "price": 5000.25}
        return [signal] * 10  # 10 identical signals
    
    @staticmethod
    def mixed_signals():
        """Random mix of different signals"""
        actions = ["BUY", "SELL"]
        tickers = ["MNQM5", "ESM5", "MESM5", "M2KM5"]
        signals = []
        for _ in range(20):
            signals.append({
                "action": random.choice(actions),
                "ticker": random.choice(tickers),
                "quantity": random.randint(1, 5),
                "price": round(random.uniform(90, 110), 2)
            })
        return signals


class WebhookStressTester:
    def __init__(self, base_url: str, webhook_token: str, webhook_secret: str):
        self.base_url = base_url
        self.webhook_token = webhook_token
        self.webhook_secret = webhook_secret
        self.webhook_url = f"{base_url}/api/v1/webhooks/{webhook_token}"
        
        # Metrics
        self.request_times: List[float] = []
        self.successful_requests = 0
        self.failed_requests = 0
        self.rate_limited_requests = 0
        self.duplicate_requests = 0
        self.error_details: Dict[str, int] = {}
        
        # Memory monitoring
        self.process = psutil.Process(os.getpid())
        self.initial_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        self.peak_memory = self.initial_memory
        
    async def send_webhook(self, session: aiohttp.ClientSession, payload: dict) -> Dict[str, Any]:
        """Send a single webhook request"""
        start_time = time.time()
        
        # Add secret to URL parameters
        url = f"{self.webhook_url}?secret={self.webhook_secret}"
        
        try:
            async with session.post(url, json=payload) as response:
                end_time = time.time()
                self.request_times.append(end_time - start_time)
                
                response_data = await response.json()
                
                if response.status == 200:
                    self.successful_requests += 1
                elif response.status == 429:
                    self.rate_limited_requests += 1
                elif response.status == 409:  # Assuming duplicate returns 409
                    self.duplicate_requests += 1
                else:
                    self.failed_requests += 1
                    error_key = f"{response.status}: {response_data.get('detail', 'Unknown')}"
                    self.error_details[error_key] = self.error_details.get(error_key, 0) + 1
                
                return {
                    "status": response.status,
                    "data": response_data,
                    "time": end_time - start_time
                }
                
        except Exception as e:
            self.failed_requests += 1
            self.error_details[str(e)] = self.error_details.get(str(e), 0) + 1
            return {
                "status": "error",
                "error": str(e),
                "time": time.time() - start_time
            }
    
    async def run_concurrent_requests(self, payloads: List[dict], concurrency: int = 10):
        """Run multiple webhook requests concurrently"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            for i, payload in enumerate(payloads):
                if i > 0 and i % concurrency == 0:
                    # Wait for batch to complete
                    await asyncio.gather(*tasks)
                    tasks = []
                    
                    # Update memory usage
                    current_memory = self.process.memory_info().rss / 1024 / 1024
                    self.peak_memory = max(self.peak_memory, current_memory)
                
                task = self.send_webhook(session, payload)
                tasks.append(task)
            
            # Complete remaining tasks
            if tasks:
                await asyncio.gather(*tasks)
    
    def print_results(self, test_name: str, duration: float):
        """Print test results"""
        print(f"\n{'='*60}")
        print(f"Test: {test_name}")
        print(f"{'='*60}")
        
        total_requests = self.successful_requests + self.failed_requests + self.rate_limited_requests + self.duplicate_requests
        
        print(f"\nRequest Statistics:")
        print(f"  Total Requests: {total_requests}")
        print(f"  Successful: {self.successful_requests} ({self.successful_requests/total_requests*100:.1f}%)")
        print(f"  Failed: {self.failed_requests} ({self.failed_requests/total_requests*100:.1f}%)")
        print(f"  Rate Limited: {self.rate_limited_requests} ({self.rate_limited_requests/total_requests*100:.1f}%)")
        print(f"  Duplicates: {self.duplicate_requests} ({self.duplicate_requests/total_requests*100:.1f}%)")
        
        if self.error_details:
            print(f"\nError Details:")
            for error, count in self.error_details.items():
                print(f"  {error}: {count}")
        
        print(f"\nPerformance Metrics:")
        print(f"  Test Duration: {duration:.2f} seconds")
        print(f"  Requests/Second: {total_requests/duration:.2f}")
        
        if self.request_times:
            print(f"  Avg Response Time: {statistics.mean(self.request_times)*1000:.2f} ms")
            print(f"  Min Response Time: {min(self.request_times)*1000:.2f} ms")
            print(f"  Max Response Time: {max(self.request_times)*1000:.2f} ms")
            print(f"  P95 Response Time: {statistics.quantiles(self.request_times, n=20)[18]*1000:.2f} ms")
        
        print(f"\nMemory Usage:")
        print(f"  Initial Memory: {self.initial_memory:.2f} MB")
        print(f"  Peak Memory: {self.peak_memory:.2f} MB")
        print(f"  Memory Increase: {self.peak_memory - self.initial_memory:.2f} MB")
        
        # Reset metrics for next test
        self.reset_metrics()
    
    def reset_metrics(self):
        """Reset metrics for next test"""
        self.request_times = []
        self.successful_requests = 0
        self.failed_requests = 0
        self.rate_limited_requests = 0
        self.duplicate_requests = 0
        self.error_details = {}


async def test_high_frequency_trading(tester: WebhookStressTester):
    """Test 1: High-frequency trading pattern"""
    print("\nStarting Test 1: High-Frequency Trading Pattern")
    print("Simulating rapid buy/sell cycles...")
    
    signals = []
    # Generate 50 buy/sell pairs (100 total signals)
    for _ in range(50):
        signals.extend(StressTestScenarios.high_frequency_trading())
    
    start_time = time.time()
    await tester.run_concurrent_requests(signals, concurrency=10)
    duration = time.time() - start_time
    
    tester.print_results("High-Frequency Trading", duration)


async def test_burst_load(tester: WebhookStressTester):
    """Test 2: Burst load - many requests at once"""
    print("\nStarting Test 2: Burst Load Test")
    print("Sending 100 requests as fast as possible...")
    
    signals = []
    for _ in range(10):
        signals.extend(StressTestScenarios.burst_trading())
    
    start_time = time.time()
    await tester.run_concurrent_requests(signals, concurrency=20)
    duration = time.time() - start_time
    
    tester.print_results("Burst Load", duration)


async def test_sustained_load(tester: WebhookStressTester):
    """Test 3: Sustained load over time"""
    print("\nStarting Test 3: Sustained Load Test")
    print("Sending requests continuously for 30 seconds...")
    
    start_time = time.time()
    requests_sent = 0
    
    while time.time() - start_time < 30:  # Run for 30 seconds
        signals = StressTestScenarios.mixed_signals()
        await tester.run_concurrent_requests(signals, concurrency=5)
        requests_sent += len(signals)
        await asyncio.sleep(0.1)  # Small delay between batches
    
    duration = time.time() - start_time
    tester.print_results("Sustained Load", duration)


async def test_memory_leak(tester: WebhookStressTester):
    """Test 4: Memory leak detection"""
    print("\nStarting Test 4: Memory Leak Detection")
    print("Sending requests continuously and monitoring memory...")
    
    memory_samples = []
    start_time = time.time()
    
    for i in range(10):  # 10 iterations
        # Send batch of requests
        signals = StressTestScenarios.mixed_signals() * 5  # 100 signals
        await tester.run_concurrent_requests(signals, concurrency=10)
        
        # Sample memory
        current_memory = tester.process.memory_info().rss / 1024 / 1024
        memory_samples.append(current_memory)
        
        print(f"  Iteration {i+1}/10 - Memory: {current_memory:.2f} MB")
        await asyncio.sleep(2)  # Wait between iterations
    
    duration = time.time() - start_time
    
    # Check for memory leak
    memory_increase = memory_samples[-1] - memory_samples[0]
    avg_increase_per_iteration = memory_increase / len(memory_samples)
    
    print(f"\nMemory Analysis:")
    print(f"  Start Memory: {memory_samples[0]:.2f} MB")
    print(f"  End Memory: {memory_samples[-1]:.2f} MB")
    print(f"  Total Increase: {memory_increase:.2f} MB")
    print(f"  Avg Increase/Iteration: {avg_increase_per_iteration:.2f} MB")
    
    if avg_increase_per_iteration > 5:  # More than 5MB per iteration
        print("  ⚠️  WARNING: Possible memory leak detected!")
    else:
        print("  ✅ Memory usage appears stable")
    
    tester.print_results("Memory Leak Detection", duration)


async def test_rate_limiting(tester: WebhookStressTester):
    """Test 5: Rate limiting effectiveness"""
    print("\nStarting Test 5: Rate Limiting Test")
    print("Testing rate limit of 10 requests/second...")
    
    # Send 20 requests as fast as possible
    signals = [{"action": "BUY", "ticker": "TEST", "quantity": 1}] * 20
    
    start_time = time.time()
    await tester.run_concurrent_requests(signals, concurrency=20)
    duration = time.time() - start_time
    
    print(f"\nRate Limiting Analysis:")
    print(f"  Requests sent: 20")
    print(f"  Time taken: {duration:.2f} seconds")
    print(f"  Expected rate limited: ~10 (half should be blocked)")
    print(f"  Actual rate limited: {tester.rate_limited_requests}")
    
    tester.print_results("Rate Limiting", duration)


async def main():
    """Run all stress tests"""
    print("="*60)
    print("Webhook Stress Testing Suite")
    print("="*60)
    print(f"Target: {BASE_URL}")
    print(f"Webhook Token: {WEBHOOK_TOKEN[:10]}...")
    print(f"Start Time: {datetime.now()}")
    
    # Initialize tester
    tester = WebhookStressTester(BASE_URL, WEBHOOK_TOKEN, WEBHOOK_SECRET)
    
    # Run tests
    tests = [
        test_high_frequency_trading,
        test_burst_load,
        test_sustained_load,
        test_memory_leak,
        test_rate_limiting
    ]
    
    for test_func in tests:
        try:
            await test_func(tester)
            await asyncio.sleep(5)  # Cool down between tests
        except Exception as e:
            print(f"\n❌ Test failed with error: {e}")
    
    print("\n" + "="*60)
    print("All tests completed!")
    print("="*60)


if __name__ == "__main__":
    # Check if server is running
    import requests
    try:
        response = requests.get(f"{BASE_URL}/docs")
        if response.status_code != 200:
            print("⚠️  Warning: Server may not be running properly")
    except:
        print("❌ Error: Cannot connect to server. Please ensure it's running.")
        exit(1)
    
    # Run stress tests
    asyncio.run(main())