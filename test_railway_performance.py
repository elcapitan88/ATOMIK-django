#!/usr/bin/env python3
"""
Railway Performance Testing Script
Tests the Railway-optimized webhook processing performance
"""

import asyncio
import aiohttp
import time
import json
import psutil
import os
from datetime import datetime
from typing import List, Dict, Any

# Configuration
TARGET_URL = "https://api.atomiktrading.io"  # Your Railway production URL
WEBHOOK_TOKEN = "Uva9KWM-i_fvwT4Bsyqwn4GNmUwCXCuUO1MRy4t9oAw"  # Your webhook token
WEBHOOK_SECRET = "1153bd34c107ff34edca215dcc12ebb00b3bb07ac0ffe22fca4df60df277034a"  # Your webhook secret
TOTAL_REQUESTS = 50  # Reduced for quicker testing

class RailwayPerformanceTester:
    def __init__(self, base_url: str, webhook_token: str, webhook_secret: str = None):
        self.base_url = base_url.rstrip('/')
        self.webhook_token = webhook_token
        self.webhook_secret = webhook_secret
        
        # Build webhook URL with secret parameter if provided
        self.webhook_url = f"{self.base_url}/api/v1/webhooks/{self.webhook_token}"
        if self.webhook_secret:
            self.webhook_url += f"?secret={self.webhook_secret}"
        
        self.results = []
        
    async def send_webhook_request(self, session: aiohttp.ClientSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send a single webhook request and measure performance"""
        start_time = time.time()
        
        try:
            async with session.post(
                self.webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                end_time = time.time()
                response_time = (end_time - start_time) * 1000  # Convert to milliseconds
                
                response_data = await response.json()
                
                return {
                    "status_code": response.status,
                    "response_time_ms": round(response_time, 2),
                    "success": response.status == 200,
                    "railway_optimized": response_data.get("railway_optimized", False),
                    "processing_time_ms": response_data.get("processing_time_ms", None),
                    "webhook_id": response_data.get("webhook_id"),
                    "response_status": response_data.get("status", "unknown")
                }
                
        except asyncio.TimeoutError:
            return {
                "status_code": 408,
                "response_time_ms": 10000,  # 10 second timeout
                "success": False,
                "error": "timeout",
                "railway_optimized": False
            }
        except Exception as e:
            end_time = time.time()
            response_time = (end_time - start_time) * 1000
            return {
                "status_code": 0,
                "response_time_ms": round(response_time, 2),
                "success": False,
                "error": str(e),
                "railway_optimized": False
            }

    async def run_performance_test(self, num_requests: int = 100) -> Dict[str, Any]:
        """Run performance test with concurrent requests"""
        print(f"\n🚀 Testing Railway-Optimized Performance")
        print(f"Target: {self.webhook_url}")
        print(f"Requests: {num_requests}")
        
        # Create test payload
        test_payload = {
            "action": "BUY",
            "symbol": "AAPL",
            "quantity": 100,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "railway_performance_test"
        }
        
        # Record initial memory
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        start_time = time.time()
        
        # Create HTTP session with connection pooling
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create tasks for concurrent requests
            tasks = []
            for i in range(num_requests):
                # Add unique identifier to each request
                payload = test_payload.copy()
                payload["request_id"] = f"railway_test_{i}_{int(time.time() * 1000)}"
                tasks.append(self.send_webhook_request(session, payload))
            
            # Execute all requests concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        total_duration = end_time - start_time
        
        # Record final memory
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Process results
        successful_requests = []
        failed_requests = []
        railway_optimized_count = 0
        rate_limited_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                failed_requests.append({"error": str(result)})
            elif result["success"]:
                successful_requests.append(result)
                if result.get("railway_optimized"):
                    railway_optimized_count += 1
            else:
                failed_requests.append(result)
                if result.get("status_code") == 429:
                    rate_limited_count += 1
        
        # Calculate statistics
        if successful_requests:
            response_times = [r["response_time_ms"] for r in successful_requests]
            processing_times = [r["processing_time_ms"] for r in successful_requests if r.get("processing_time_ms")]
            
            stats = {
                "total_requests": num_requests,
                "successful": len(successful_requests),
                "failed": len(failed_requests),
                "rate_limited": rate_limited_count,
                "railway_optimized": railway_optimized_count,
                "success_rate": round((len(successful_requests) / num_requests) * 100, 1),
                
                "response_time_stats": {
                    "avg_ms": round(sum(response_times) / len(response_times), 2),
                    "min_ms": round(min(response_times), 2),
                    "max_ms": round(max(response_times), 2),
                    "p95_ms": round(sorted(response_times)[int(len(response_times) * 0.95)], 2)
                },
                
                "test_duration": {
                    "total_seconds": round(total_duration, 2),
                    "requests_per_second": round(num_requests / total_duration, 2)
                },
                
                "memory_usage": {
                    "initial_mb": round(initial_memory, 2),
                    "final_mb": round(final_memory, 2),
                    "increase_mb": round(memory_increase, 2)
                }
            }
            
            # Processing time stats (if available)
            if processing_times:
                stats["processing_time_stats"] = {
                    "avg_ms": round(sum(processing_times) / len(processing_times), 2),
                    "min_ms": round(min(processing_times), 2),
                    "max_ms": round(max(processing_times), 2),
                    "p95_ms": round(sorted(processing_times)[int(len(processing_times) * 0.95)], 2)
                }
        else:
            stats = {
                "total_requests": num_requests,
                "successful": 0,
                "failed": len(failed_requests),
                "error": "No successful requests"
            }
        
        return stats

    def print_results(self, stats: Dict[str, Any]):
        """Print formatted test results"""
        print(f"\n{'='*60}")
        print(f"🏆 RAILWAY PERFORMANCE TEST RESULTS")
        print(f"{'='*60}")
        
        if stats.get("error"):
            print(f"❌ Test failed: {stats['error']}")
            return
        
        # Request Statistics
        print(f"\n📊 Request Statistics:")
        print(f"  Total Requests: {stats['total_requests']}")
        print(f"  Successful: {stats['successful']} ({stats['success_rate']}%)")
        print(f"  Failed: {stats['failed']}")
        print(f"  Rate Limited: {stats['rate_limited']}")
        print(f"  Railway Optimized: {stats['railway_optimized']}")
        
        # Performance Metrics
        if "response_time_stats" in stats:
            rt = stats["response_time_stats"]
            print(f"\n⚡ Response Time Performance:")
            print(f"  Average: {rt['avg_ms']}ms")
            print(f"  Min: {rt['min_ms']}ms")
            print(f"  Max: {rt['max_ms']}ms")
            print(f"  P95: {rt['p95_ms']}ms")
            
            # Performance assessment
            avg_time = rt['avg_ms']
            if avg_time < 150:
                print(f"  🚀 EXCELLENT: Response time under 150ms!")
            elif avg_time < 200:
                print(f"  ✅ GOOD: Response time under 200ms")
            elif avg_time < 300:
                print(f"  ⚠️  ACCEPTABLE: Response time under 300ms")
            else:
                print(f"  ❌ NEEDS IMPROVEMENT: Response time over 300ms")
        
        # Processing Time (Server-side)
        if "processing_time_stats" in stats:
            pt = stats["processing_time_stats"]
            print(f"\n🔧 Server Processing Time:")
            print(f"  Average: {pt['avg_ms']}ms")
            print(f"  Min: {pt['min_ms']}ms")
            print(f"  Max: {pt['max_ms']}ms")
            print(f"  P95: {pt['p95_ms']}ms")
        
        # Test Performance
        td = stats["test_duration"]
        print(f"\n🎯 Test Performance:")
        print(f"  Duration: {td['total_seconds']} seconds")
        print(f"  Throughput: {td['requests_per_second']} req/sec")
        
        # Memory Usage
        mem = stats["memory_usage"]
        print(f"\n💾 Memory Usage:")
        print(f"  Initial: {mem['initial_mb']} MB")
        print(f"  Final: {mem['final_mb']} MB")
        print(f"  Increase: {mem['increase_mb']} MB")
        
        # Railway Optimization Status
        opt_rate = (stats['railway_optimized'] / stats['successful']) * 100 if stats['successful'] > 0 else 0
        print(f"\n🚄 Railway Optimization:")
        print(f"  Optimized Requests: {stats['railway_optimized']}/{stats['successful']} ({opt_rate:.1f}%)")
        
        if opt_rate > 90:
            print(f"  🎉 Railway optimization is working perfectly!")
        elif opt_rate > 50:
            print(f"  ✅ Railway optimization is working")
        else:
            print(f"  ⚠️  Railway optimization may not be active")

async def main():
    """Main test execution"""
    print("🔥 Railway Performance Testing Suite")
    print("=" * 60)
    
    tester = RailwayPerformanceTester(TARGET_URL, WEBHOOK_TOKEN, WEBHOOK_SECRET)
    
    # Test 1: Quick burst test
    print("\n🏃‍♂️ Test 1: Quick Burst Test (50 requests)")
    stats1 = await tester.run_performance_test(50)
    tester.print_results(stats1)
    
    # Wait a moment
    await asyncio.sleep(2)
    
    # Test 2: Sustained load test
    print(f"\n🏋️‍♂️ Test 2: Sustained Load Test ({TOTAL_REQUESTS} requests)")
    stats2 = await tester.run_performance_test(TOTAL_REQUESTS)
    tester.print_results(stats2)
    
    # Summary comparison
    if stats1.get("response_time_stats") and stats2.get("response_time_stats"):
        print(f"\n📈 PERFORMANCE COMPARISON:")
        print(f"Burst Test Avg: {stats1['response_time_stats']['avg_ms']}ms")
        print(f"Load Test Avg: {stats2['response_time_stats']['avg_ms']}ms")
        
        if stats2['response_time_stats']['avg_ms'] < 200:
            print(f"🎯 Target achieved! Response time under 200ms")
        else:
            print(f"📊 Baseline established: {stats2['response_time_stats']['avg_ms']}ms")
    
    print(f"\n✅ Testing complete! Check Railway logs for optimization details.")

if __name__ == "__main__":
    asyncio.run(main())