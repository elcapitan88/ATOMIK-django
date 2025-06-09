#!/usr/bin/env python3
"""
Server Health Monitoring Script
Monitors server health during stress testing
"""

import psutil
import time
import requests
import json
from datetime import datetime
import subprocess
import os

class ServerHealthMonitor:
    def __init__(self, base_url="https://api.atomiktrading.io", process_name="uvicorn"):
        self.base_url = base_url
        self.process_name = process_name
        self.start_time = time.time()
        
        # Find server process
        self.server_process = None
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if process_name in proc.info['name'] or any(process_name in arg for arg in proc.info['cmdline']):
                    self.server_process = psutil.Process(proc.info['pid'])
                    print(f"Found server process: PID {proc.info['pid']}")
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        if not self.server_process:
            print(f"⚠️  Warning: Could not find {process_name} process")
        
        # Metrics storage
        self.metrics = {
            "timestamps": [],
            "cpu_percent": [],
            "memory_mb": [],
            "connections": [],
            "threads": [],
            "file_descriptors": [],
            "response_times": [],
            "redis_connections": [],
            "db_connections": []
        }
        
        # Alert thresholds
        self.thresholds = {
            "cpu_percent": 80,
            "memory_mb": 1024,  # 1GB
            "response_time_ms": 1000,
            "connections": 1000
        }
        
        self.alerts_triggered = []
    
    def check_server_health(self):
        """Check server health metrics"""
        timestamp = time.time() - self.start_time
        self.metrics["timestamps"].append(timestamp)
        
        # CPU and Memory
        if self.server_process:
            try:
                cpu_percent = self.server_process.cpu_percent(interval=0.1)
                memory_mb = self.server_process.memory_info().rss / 1024 / 1024
                connections = len(self.server_process.connections())
                threads = self.server_process.num_threads()
                fds = self.server_process.num_fds() if hasattr(self.server_process, 'num_fds') else 0
                
                self.metrics["cpu_percent"].append(cpu_percent)
                self.metrics["memory_mb"].append(memory_mb)
                self.metrics["connections"].append(connections)
                self.metrics["threads"].append(threads)
                self.metrics["file_descriptors"].append(fds)
                
                # Check thresholds
                if cpu_percent > self.thresholds["cpu_percent"]:
                    self.trigger_alert(f"High CPU usage: {cpu_percent:.1f}%")
                
                if memory_mb > self.thresholds["memory_mb"]:
                    self.trigger_alert(f"High memory usage: {memory_mb:.1f} MB")
                
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                print("❌ Lost connection to server process")
                self.server_process = None
        
        # API Response Time
        try:
            start = time.time()
            response = requests.get(f"{self.base_url}/api/v1/monitoring/health", timeout=5)
            response_time = (time.time() - start) * 1000  # ms
            self.metrics["response_times"].append(response_time)
            
            if response_time > self.thresholds["response_time_ms"]:
                self.trigger_alert(f"Slow response time: {response_time:.0f}ms")
                
        except Exception as e:
            self.metrics["response_times"].append(-1)
            self.trigger_alert(f"API not responding: {str(e)}")
        
        # Check Redis connections (if monitoring endpoint available)
        try:
            response = requests.get(f"{self.base_url}/api/v1/monitoring/redis/stats", timeout=2)
            if response.status_code == 200:
                data = response.json()
                redis_connections = data.get("connected_clients", 0)
                self.metrics["redis_connections"].append(redis_connections)
        except:
            self.metrics["redis_connections"].append(-1)
        
        # Check database connections (if monitoring endpoint available)
        try:
            response = requests.get(f"{self.base_url}/api/v1/monitoring/database/stats", timeout=2)
            if response.status_code == 200:
                data = response.json()
                db_connections = data.get("active_connections", 0)
                self.metrics["db_connections"].append(db_connections)
        except:
            self.metrics["db_connections"].append(-1)
    
    def trigger_alert(self, message):
        """Trigger an alert"""
        alert = {
            "timestamp": datetime.now().isoformat(),
            "message": message
        }
        self.alerts_triggered.append(alert)
        print(f"🚨 ALERT: {message}")
    
    def print_current_status(self):
        """Print current status"""
        if not self.metrics["timestamps"]:
            return
        
        # Clear screen (works on Unix-like systems)
        os.system('clear' if os.name != 'nt' else 'cls')
        
        print("="*60)
        print(f"Server Health Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        
        if self.server_process:
            latest_idx = -1
            print(f"\n📊 Current Metrics:")
            print(f"  CPU Usage: {self.metrics['cpu_percent'][latest_idx]:.1f}%")
            print(f"  Memory Usage: {self.metrics['memory_mb'][latest_idx]:.1f} MB")
            print(f"  Active Connections: {self.metrics['connections'][latest_idx]}")
            print(f"  Threads: {self.metrics['threads'][latest_idx]}")
            print(f"  File Descriptors: {self.metrics['file_descriptors'][latest_idx]}")
        
        if self.metrics["response_times"] and self.metrics["response_times"][-1] >= 0:
            print(f"  API Response Time: {self.metrics['response_times'][-1]:.0f} ms")
        
        if self.metrics["redis_connections"] and self.metrics["redis_connections"][-1] >= 0:
            print(f"  Redis Connections: {self.metrics['redis_connections'][-1]}")
        
        if self.metrics["db_connections"] and self.metrics["db_connections"][-1] >= 0:
            print(f"  Database Connections: {self.metrics['db_connections'][-1]}")
        
        # Show recent alerts
        if self.alerts_triggered:
            print(f"\n🚨 Recent Alerts (last 5):")
            for alert in self.alerts_triggered[-5:]:
                print(f"  {alert['timestamp']}: {alert['message']}")
        
        # Show trends
        if len(self.metrics["timestamps"]) > 10:
            print(f"\n📈 Trends (last 30 seconds):")
            
            # CPU trend
            recent_cpu = self.metrics["cpu_percent"][-30:]
            if recent_cpu:
                avg_cpu = sum(recent_cpu) / len(recent_cpu)
                max_cpu = max(recent_cpu)
                print(f"  CPU: avg={avg_cpu:.1f}%, max={max_cpu:.1f}%")
            
            # Memory trend
            recent_memory = self.metrics["memory_mb"][-30:]
            if recent_memory:
                start_mem = recent_memory[0]
                end_mem = recent_memory[-1]
                mem_change = end_mem - start_mem
                print(f"  Memory: start={start_mem:.1f}MB, end={end_mem:.1f}MB, change={mem_change:+.1f}MB")
    
    def save_report(self):
        """Save monitoring report"""
        report = {
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "duration_seconds": time.time() - self.start_time,
            "metrics": self.metrics,
            "alerts": self.alerts_triggered,
            "summary": {
                "max_cpu_percent": max(self.metrics["cpu_percent"]) if self.metrics["cpu_percent"] else 0,
                "max_memory_mb": max(self.metrics["memory_mb"]) if self.metrics["memory_mb"] else 0,
                "avg_response_time_ms": sum(t for t in self.metrics["response_times"] if t >= 0) / len([t for t in self.metrics["response_times"] if t >= 0]) if self.metrics["response_times"] else 0,
                "total_alerts": len(self.alerts_triggered)
            }
        }
        
        filename = f"server_health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n📄 Report saved to: {filename}")
        return filename
    
    def run(self, duration_seconds=300, interval=1):
        """Run monitoring for specified duration"""
        print(f"Starting server health monitoring for {duration_seconds} seconds...")
        print(f"Monitoring interval: {interval} second(s)")
        print("Press Ctrl+C to stop early and save report\n")
        
        try:
            end_time = time.time() + duration_seconds
            
            while time.time() < end_time:
                self.check_server_health()
                self.print_current_status()
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
        
        # Save final report
        report_file = self.save_report()
        
        # Print final summary
        print("\n" + "="*60)
        print("Monitoring Summary")
        print("="*60)
        print(f"Duration: {time.time() - self.start_time:.1f} seconds")
        print(f"Total Alerts: {len(self.alerts_triggered)}")
        
        if self.metrics["cpu_percent"]:
            print(f"Max CPU: {max(self.metrics['cpu_percent']):.1f}%")
        
        if self.metrics["memory_mb"]:
            print(f"Max Memory: {max(self.metrics['memory_mb']):.1f} MB")
            print(f"Memory Growth: {self.metrics['memory_mb'][-1] - self.metrics['memory_mb'][0]:+.1f} MB")
        
        if self.metrics["response_times"]:
            valid_times = [t for t in self.metrics["response_times"] if t >= 0]
            if valid_times:
                print(f"Avg Response Time: {sum(valid_times)/len(valid_times):.0f} ms")
                print(f"Max Response Time: {max(valid_times):.0f} ms")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor server health during stress testing")
    parser.add_argument("--url", default="http://localhost:8000", help="Server base URL")
    parser.add_argument("--duration", type=int, default=300, help="Monitoring duration in seconds")
    parser.add_argument("--interval", type=int, default=1, help="Check interval in seconds")
    parser.add_argument("--process", default="uvicorn", help="Server process name")
    
    args = parser.parse_args()
    
    monitor = ServerHealthMonitor(base_url=args.url, process_name=args.process)
    monitor.run(duration_seconds=args.duration, interval=args.interval)