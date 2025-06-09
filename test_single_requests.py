#!/usr/bin/env python3
"""
Single Request Performance Test
Tests individual webhook requests with proper spacing to measure true performance
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime
from typing import List, Dict, Any

# Configuration
TARGET_URL = "https://api.atomiktrading.io"
WEBHOOK_TOKEN = "Uva9KWM-i_fvwT4Bsyqwn4GNmUwCXCuUO1MRy4t9oAw"
WEBHOOK_SECRET = "1153bd34c107ff34edca215dcc12ebb00b3bb07ac0ffe22fca4df60df277034a"
TOTAL_REQUESTS = 20  # Fewer requests, spaced out
DELAY_BETWEEN_REQUESTS = 2  # 2 seconds between requests

class SingleRequestTester:
    def __init__(self, base_url: str, webhook_token: str, webhook_secret: str = None):
        self.base_url = base_url.rstrip('/')
        self.webhook_token = webhook_token
        self.webhook_secret = webhook_secret
        
        # Build webhook URL with secret parameter
        self.webhook_url = f"{self.base_url}/api/v1/webhooks/{self.webhook_token}"
        if self.webhook_secret:
            self.webhook_url += f"?secret={self.webhook_secret}"
        
        self.results = []
        
    async def send_single_request(self, request_id: int) -> Dict[str, Any]:
        """Send a single webhook request and measure all timing metrics"""
        
        # Create test payload
        test_payload = {
            "action": "BUY",
            "symbol": "AAPL", 
            "quantity": 100,
            "timestamp": datetime.now().isoformat(),
            "source": f"single_test_{request_id}",
            "request_id": request_id
        }
        
        print(f"🚀 Sending request {request_id}...")
        start_time = time.time()
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.webhook_url,
                    json=test_payload
                ) as response:
                    end_time = time.time()
                    total_response_time = (end_time - start_time) * 1000  # ms
                    
                    response_data = await response.json()
                    
                    result = {
                        "request_id": request_id,
                        "status_code": response.status,
                        "total_response_time_ms": round(total_response_time, 2),
                        "success": response.status == 200,
                        "railway_optimized": response_data.get("railway_optimized", False),
                        "server_processing_time_ms": response_data.get("processing_time_ms"),
                        "webhook_id": response_data.get("webhook_id"),
                        "response_status": response_data.get("status", "unknown"),
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    # Calculate network time (total - server processing)
                    if result["server_processing_time_ms"]:
                        result["network_time_ms"] = round(
                            total_response_time - result["server_processing_time_ms"], 2
                        )
                    
                    # Print real-time results
                    status = "✅" if result["success"] else "❌"
                    rail_opt = "🚄" if result["railway_optimized"] else "🐌"
                    
                    print(f"  {status} Request {request_id}: {total_response_time:.1f}ms total")
                    if result.get("server_processing_time_ms"):
                        print(f"     Server: {result['server_processing_time_ms']:.1f}ms {rail_opt}")
                        print(f"     Network: {result.get('network_time_ms', 'N/A'):.1f}ms")
                    
                    return result
                    
        except Exception as e:
            end_time = time.time()
            total_response_time = (end_time - start_time) * 1000
            
            result = {
                "request_id": request_id,
                "status_code": 0,
                "total_response_time_ms": round(total_response_time, 2),
                "success": False,
                "error": str(e),
                "railway_optimized": False,
                "timestamp": datetime.now().isoformat()
            }
            
            print(f"  ❌ Request {request_id}: FAILED - {str(e)}")
            return result

    async def run_spaced_test(self, num_requests: int, delay_seconds: float) -> Dict[str, Any]:
        """Run spaced-out individual requests"""
        
        print(f"\n🧪 Single Request Performance Test")
        print(f"Target: {self.webhook_url}")
        print(f"Requests: {num_requests}")
        print(f"Delay: {delay_seconds} seconds between requests")
        print(f"Expected duration: ~{num_requests * delay_seconds} seconds")
        print(f"=" * 60)
        
        results = []
        test_start_time = time.time()
        
        for i in range(num_requests):
            # Send request
            result = await self.send_single_request(i + 1)
            results.append(result)
            
            # Wait before next request (except for last one)
            if i < num_requests - 1:
                print(f"   ⏳ Waiting {delay_seconds}s...\n")
                await asyncio.sleep(delay_seconds)
        
        test_end_time = time.time()
        total_test_duration = test_end_time - test_start_time
        
        # Analyze results
        successful_requests = [r for r in results if r["success"]]
        failed_requests = [r for r in results if not r["success"]]
        
        if successful_requests:
            total_times = [r["total_response_time_ms"] for r in successful_requests]
            server_times = [r["server_processing_time_ms"] for r in successful_requests if r.get("server_processing_time_ms")]
            network_times = [r["network_time_ms"] for r in successful_requests if r.get("network_time_ms")]
            railway_optimized_count = sum(1 for r in successful_requests if r.get("railway_optimized"))
            
            stats = {
                "test_info": {
                    "total_requests": num_requests,
                    "successful": len(successful_requests),
                    "failed": len(failed_requests),
                    "success_rate": round((len(successful_requests) / num_requests) * 100, 1),
                    "railway_optimized": railway_optimized_count,
                    "test_duration_seconds": round(total_test_duration, 1)
                },
                
                "total_response_times": {
                    "avg_ms": round(sum(total_times) / len(total_times), 2),
                    "min_ms": round(min(total_times), 2),
                    "max_ms": round(max(total_times), 2),
                    "median_ms": round(sorted(total_times)[len(total_times)//2], 2)
                }
            }
            
            if server_times:
                stats["server_processing_times"] = {
                    "avg_ms": round(sum(server_times) / len(server_times), 2),
                    "min_ms": round(min(server_times), 2),
                    "max_ms": round(max(server_times), 2),
                    "median_ms": round(sorted(server_times)[len(server_times)//2], 2)
                }
            
            if network_times:
                stats["network_times"] = {
                    "avg_ms": round(sum(network_times) / len(network_times), 2),
                    "min_ms": round(min(network_times), 2),
                    "max_ms": round(max(network_times), 2),
                    "median_ms": round(sorted(network_times)[len(network_times)//2], 2)
                }
                
            stats["individual_results"] = successful_requests
            
        else:
            stats = {
                "test_info": {
                    "total_requests": num_requests,
                    "successful": 0,
                    "failed": len(failed_requests),
                    "error": "No successful requests"
                },
                "individual_results": results
            }
        
        return stats

    def print_results(self, stats: Dict[str, Any]):
        """Print formatted test results"""
        
        print(f"\n{'='*60}")
        print(f"📊 SINGLE REQUEST TEST RESULTS")
        print(f"{'='*60}")
        
        info = stats["test_info"]
        
        if info.get("error"):
            print(f"❌ Test failed: {info['error']}")
            return
        
        # Test Overview
        print(f"\n📋 Test Overview:")
        print(f"  Total Requests: {info['total_requests']}")
        print(f"  Successful: {info['successful']} ({info['success_rate']}%)")
        print(f"  Failed: {info['failed']}")
        print(f"  Railway Optimized: {info['railway_optimized']}")
        print(f"  Test Duration: {info['test_duration_seconds']} seconds")
        
        # Response Time Analysis
        if "total_response_times" in stats:
            rt = stats["total_response_times"]
            print(f"\n⚡ Total Response Times:")
            print(f"  Average: {rt['avg_ms']}ms")
            print(f"  Median: {rt['median_ms']}ms")
            print(f"  Range: {rt['min_ms']}ms - {rt['max_ms']}ms")
            
            # Performance assessment
            avg_time = rt['avg_ms']
            if avg_time < 150:
                print(f"  🚀 EXCELLENT: Under 150ms")
            elif avg_time < 300:
                print(f"  ✅ GOOD: Under 300ms") 
            elif avg_time < 500:
                print(f"  ⚠️  ACCEPTABLE: Under 500ms")
            else:
                print(f"  ❌ NEEDS IMPROVEMENT: Over 500ms")
        
        # Server Processing Times
        if "server_processing_times" in stats:
            st = stats["server_processing_times"]
            print(f"\n🔧 Server Processing Times:")
            print(f"  Average: {st['avg_ms']}ms")
            print(f"  Median: {st['median_ms']}ms")
            print(f"  Range: {st['min_ms']}ms - {st['max_ms']}ms")
        
        # Network Times
        if "network_times" in stats:
            nt = stats["network_times"]
            print(f"\n🌐 Network Latency:")
            print(f"  Average: {nt['avg_ms']}ms")
            print(f"  Median: {nt['median_ms']}ms")
            print(f"  Range: {nt['min_ms']}ms - {nt['max_ms']}ms")
            
            # Network vs Server breakdown
            if "server_processing_times" in stats:
                server_avg = stats["server_processing_times"]["avg_ms"]
                network_avg = nt["avg_ms"]
                total_avg = stats["total_response_times"]["avg_ms"]
                
                print(f"\n📈 Performance Breakdown:")
                print(f"  Server Processing: {server_avg}ms ({(server_avg/total_avg)*100:.1f}%)")
                print(f"  Network Latency: {network_avg}ms ({(network_avg/total_avg)*100:.1f}%)")

async def main():
    """Main test execution"""
    print("🎯 Single Request Performance Testing")
    print("=" * 60)
    print("This test sends individual requests with delays to measure true performance")
    print("Turn off your VPN for the most accurate network measurements!")
    
    tester = SingleRequestTester(TARGET_URL, WEBHOOK_TOKEN, WEBHOOK_SECRET)
    
    # Run spaced test
    stats = await tester.run_spaced_test(TOTAL_REQUESTS, DELAY_BETWEEN_REQUESTS)
    tester.print_results(stats)
    
    # Compare to previous baseline
    if "total_response_times" in stats:
        current_avg = stats["total_response_times"]["avg_ms"]
        previous_baseline = 281  # Your previous stress test average
        
        print(f"\n🔬 COMPARISON TO BASELINE:")
        print(f"Previous (stress test): ~{previous_baseline}ms average")
        print(f"Current (single requests): {current_avg}ms average")
        
        if current_avg < previous_baseline:
            improvement = previous_baseline - current_avg
            improvement_pct = (improvement / previous_baseline) * 100
            print(f"🎉 IMPROVEMENT: {improvement:.1f}ms faster ({improvement_pct:.1f}% better)")
        else:
            regression = current_avg - previous_baseline
            regression_pct = (regression / previous_baseline) * 100
            print(f"⚠️  REGRESSION: {regression:.1f}ms slower ({regression_pct:.1f}% worse)")
    
    print(f"\n✅ Single request testing complete!")

if __name__ == "__main__":
    asyncio.run(main())