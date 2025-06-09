#!/bin/bash

# Webhook Stress Test Runner
# This script runs the health monitor and stress tests together

echo "=========================================="
echo "Webhook Stress Test Suite"
echo "=========================================="

# Configuration
WEBHOOK_TOKEN="Uva9KWM-i_fvwT4Bsyqwn4GNmUwCXCuUO1MRy4t9oAw"
WEBHOOK_SECRET="1153bd34c107ff34edca215dcc12ebb00b3bb07ac0ffe22fca4df60df277034a"
SERVER_URL="https://api.atomiktrading.io"

# Check if server is running
echo "Checking server status..."
if ! curl -s "$SERVER_URL/docs" > /dev/null; then
    echo "❌ Error: Server is not running at $SERVER_URL"
    echo "Please start the server first with: uvicorn main:app --reload"
    exit 1
fi

echo "✅ Server is running"

# Create a test webhook if needed
echo ""
echo "To create a test webhook, run:"
echo "curl -X POST $SERVER_URL/api/v1/webhooks/ \\"
echo "  -H 'Authorization: Bearer YOUR_TOKEN' \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"name\": \"Stress Test Webhook\"}'"
echo ""

# Update the Python scripts with webhook credentials
echo "Please update the following in stress_test_webhooks.py:"
echo "  WEBHOOK_TOKEN = \"$WEBHOOK_TOKEN\""
echo "  WEBHOOK_SECRET = \"$WEBHOOK_SECRET\""
echo ""

# Start monitoring in background
echo "Starting server health monitor..."
python monitor_server_health.py --duration 600 --interval 1 > monitor.log 2>&1 &
MONITOR_PID=$!
echo "Monitor started with PID: $MONITOR_PID"

# Wait a moment for monitor to start
sleep 2

# Run stress tests
echo ""
echo "Starting stress tests in 5 seconds..."
echo "Press Ctrl+C to stop"
sleep 5

python stress_test_webhooks.py

# Stop monitor
echo ""
echo "Stopping monitor..."
kill $MONITOR_PID 2>/dev/null

# Display results
echo ""
echo "=========================================="
echo "Test Complete!"
echo "=========================================="
echo "Check the following files for results:"
echo "  - monitor.log (health monitoring output)"
echo "  - server_health_report_*.json (detailed metrics)"
echo ""

# Check for memory leaks
if [ -f "server_health_report_*.json" ]; then
    echo "Analyzing results for issues..."
    python -c "
import json
import glob

files = glob.glob('server_health_report_*.json')
if files:
    with open(files[-1], 'r') as f:
        data = json.load(f)
    
    print(f'Max CPU Usage: {data[\"summary\"][\"max_cpu_percent\"]:.1f}%')
    print(f'Max Memory Usage: {data[\"summary\"][\"max_memory_mb\"]:.1f} MB')
    print(f'Total Alerts: {data[\"summary\"][\"total_alerts\"]}')
    
    # Check for memory leak
    if 'memory_mb' in data['metrics'] and len(data['metrics']['memory_mb']) > 10:
        start_mem = data['metrics']['memory_mb'][0]
        end_mem = data['metrics']['memory_mb'][-1]
        mem_increase = end_mem - start_mem
        
        if mem_increase > 100:  # More than 100MB increase
            print(f'⚠️  WARNING: Possible memory leak detected! Memory increased by {mem_increase:.1f} MB')
        else:
            print(f'✅ Memory usage stable (change: {mem_increase:+.1f} MB)')
"
fi