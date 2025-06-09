# DigitalOcean Webhook Performance Testing Guide

This guide will walk you through setting up a DigitalOcean Virtual Machine (Droplet) to test webhook performance from a location close to Railway's servers.

## Prerequisites

- A DigitalOcean account (sign up at https://www.digitalocean.com)
- A credit card or PayPal account for billing
- Basic familiarity with terminal/command prompt

## Step 1: Create Your Droplet

### 1.1 Log into DigitalOcean
1. Go to https://cloud.digitalocean.com
2. Log in with your credentials
3. Click the green **"Create"** button in the top right
4. Select **"Droplets"** from the dropdown

### 1.2 Configure Your Droplet

**Choose Region:**
- Select **New York (NYC1, NYC2, or NYC3)** - these are closest to Railway's infrastructure
- Alternative: **Toronto (TOR1)** if NYC is unavailable

**Choose Image:**
- Select **Ubuntu 22.04 LTS** (recommended for stability and support)

**Choose Size:**
- For webhook testing, select **Basic** plan
- Choose **Regular Intel with SSD**
- Select the **$6/month** option (1 GB RAM, 1 vCPU, 25 GB SSD)
  - This provides: 1000 GB transfer, sufficient for testing

**Choose Authentication:**
- Select **SSH Key** (more secure) or **Password** (easier for beginners)
- If using SSH Key:
  - Click **"New SSH Key"**
  - Follow the instructions to generate one
- If using Password:
  - You'll receive it via email after creation

**Finalize:**
- Give your droplet a hostname like `webhook-test-nyc`
- Click **"Create Droplet"**
- Wait 30-60 seconds for creation

## Step 2: Connect to Your Droplet via SSH

### 2.1 Find Your Droplet's IP Address
- Go to your DigitalOcean dashboard
- Find your droplet and note the IP address (e.g., `157.245.123.456`)

### 2.2 Connect Using SSH

**On Windows (using PowerShell or Command Prompt):**
```bash
ssh root@YOUR_DROPLET_IP
```

**On Mac/Linux (using Terminal):**
```bash
ssh root@YOUR_DROPLET_IP
```

**If you used a password:**
- Enter the password when prompted
- First login may ask you to change the password

**If you used SSH key:**
- Connection should be automatic if your key is properly configured

## Step 3: Install Python and Dependencies

Once connected to your droplet, run these commands:

### 3.1 Update System Packages
```bash
# Update package list
sudo apt update

# Upgrade installed packages
sudo apt upgrade -y
```

### 3.2 Install Python and Essential Tools
```bash
# Install Python 3.10+ and pip
sudo apt install python3 python3-pip python3-venv -y

# Install useful tools
sudo apt install curl wget git nano -y

# Verify Python installation
python3 --version
```

### 3.3 Create a Project Directory
```bash
# Create directory for webhook testing
mkdir ~/webhook-testing
cd ~/webhook-testing

# Create Python virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate
```

### 3.4 Install Python Dependencies
```bash
# Install required packages for webhook testing
pip install requests aiohttp fastapi uvicorn httpx

# Install performance monitoring tools
pip install psutil memory-profiler
```

## Step 4: Upload and Run Test Scripts

### 4.1 Create a Simple Webhook Test Script

Create a file called `webhook_test.py`:

```bash
nano webhook_test.py
```

Paste this test script:

```python
import time
import requests
import statistics
from datetime import datetime

def test_webhook_performance(webhook_url, num_tests=10):
    """Test webhook response times"""
    
    response_times = []
    
    print(f"Testing webhook: {webhook_url}")
    print(f"Running {num_tests} tests...\n")
    
    for i in range(num_tests):
        # Sample webhook payload
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "test_number": i + 1,
            "source": "digitalocean-nyc"
        }
        
        # Measure response time
        start_time = time.time()
        try:
            response = requests.post(webhook_url, json=payload, timeout=30)
            end_time = time.time()
            
            response_time = (end_time - start_time) * 1000  # Convert to ms
            response_times.append(response_time)
            
            print(f"Test {i+1}: {response_time:.2f}ms - Status: {response.status_code}")
            
        except Exception as e:
            print(f"Test {i+1}: Failed - {str(e)}")
        
        # Small delay between tests
        time.sleep(1)
    
    # Calculate statistics
    if response_times:
        print(f"\n--- Performance Summary ---")
        print(f"Average: {statistics.mean(response_times):.2f}ms")
        print(f"Median: {statistics.median(response_times):.2f}ms")
        print(f"Min: {min(response_times):.2f}ms")
        print(f"Max: {max(response_times):.2f}ms")
        print(f"Std Dev: {statistics.stdev(response_times):.2f}ms" if len(response_times) > 1 else "")

if __name__ == "__main__":
    # Replace with your actual webhook URL
    WEBHOOK_URL = "https://your-app.railway.app/webhook"
    
    test_webhook_performance(WEBHOOK_URL, num_tests=20)
```

Save and exit (Ctrl+X, then Y, then Enter).

### 4.2 Create an Advanced Load Test Script

Create `load_test.py`:

```bash
nano load_test.py
```

Paste this script:

```python
import asyncio
import aiohttp
import time
from datetime import datetime
import statistics

async def send_webhook(session, url, payload):
    """Send a single webhook request"""
    start_time = time.time()
    try:
        async with session.post(url, json=payload) as response:
            end_time = time.time()
            return {
                "status": response.status,
                "time": (end_time - start_time) * 1000,
                "success": True
            }
    except Exception as e:
        end_time = time.time()
        return {
            "status": 0,
            "time": (end_time - start_time) * 1000,
            "success": False,
            "error": str(e)
        }

async def load_test(webhook_url, concurrent_requests=10, total_requests=100):
    """Run concurrent load test"""
    
    print(f"Load Testing: {webhook_url}")
    print(f"Concurrent requests: {concurrent_requests}")
    print(f"Total requests: {total_requests}\n")
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        results = []
        
        start_time = time.time()
        
        for i in range(total_requests):
            payload = {
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": i + 1,
                "source": "digitalocean-load-test"
            }
            
            task = send_webhook(session, webhook_url, payload)
            tasks.append(task)
            
            # Control concurrency
            if len(tasks) >= concurrent_requests:
                batch_results = await asyncio.gather(*tasks)
                results.extend(batch_results)
                tasks = []
        
        # Handle remaining tasks
        if tasks:
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Analyze results
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        response_times = [r["time"] for r in successful]
        
        print(f"\n--- Load Test Results ---")
        print(f"Total time: {total_time:.2f} seconds")
        print(f"Requests per second: {len(results) / total_time:.2f}")
        print(f"Successful: {len(successful)}")
        print(f"Failed: {len(failed)}")
        
        if response_times:
            print(f"\n--- Response Time Statistics ---")
            print(f"Average: {statistics.mean(response_times):.2f}ms")
            print(f"Median: {statistics.median(response_times):.2f}ms")
            print(f"Min: {min(response_times):.2f}ms")
            print(f"Max: {max(response_times):.2f}ms")
            print(f"95th percentile: {statistics.quantiles(response_times, n=20)[18]:.2f}ms")

if __name__ == "__main__":
    # Replace with your actual webhook URL
    WEBHOOK_URL = "https://your-app.railway.app/webhook"
    
    # Run load test
    asyncio.run(load_test(WEBHOOK_URL, concurrent_requests=20, total_requests=200))
```

### 4.3 Alternative: Upload Files Using SCP

From your local machine, you can upload files directly:

**Windows (PowerShell):**
```bash
scp C:\path\to\your\test_script.py root@YOUR_DROPLET_IP:~/webhook-testing/
```

**Mac/Linux:**
```bash
scp /path/to/your/test_script.py root@YOUR_DROPLET_IP:~/webhook-testing/
```

### 4.4 Run the Tests

```bash
# Make sure virtual environment is activated
cd ~/webhook-testing
source venv/bin/activate

# Run simple test
python3 webhook_test.py

# Run load test
python3 load_test.py
```

## Step 5: Monitor System Resources During Testing

### 5.1 Install Monitoring Tools
```bash
# Install htop for real-time monitoring
sudo apt install htop -y

# Install network monitoring tool
sudo apt install iftop -y
```

### 5.2 Monitor During Tests

Open a second SSH session and run:
```bash
# Monitor CPU and memory
htop

# Or use built-in tools
# Watch network traffic
iftop

# Monitor system resources
vmstat 1
```

## Expected Costs

### Droplet Costs
- **Basic Droplet ($6/month)**: ~$0.009/hour
- **For 1 hour of testing**: ~$0.01
- **For 1 day of testing**: ~$0.20
- **For 1 week of testing**: ~$1.40

### Bandwidth Costs
- First 1000 GB included free
- Webhook testing typically uses < 1 GB

**Total Expected Cost for Testing**: $0.20 - $2.00

## Cleanup Instructions

### Option 1: Destroy Droplet (Recommended)
1. Go to DigitalOcean dashboard
2. Click on your droplet
3. Click **"Destroy"** in the left menu
4. Select **"Destroy Droplet"**
5. Confirm destruction
6. All billing stops immediately

### Option 2: Power Off (Keep for Later)
1. Go to DigitalOcean dashboard
2. Click on your droplet
3. Click **"Power"** → **"Power Off"**
4. You'll still be charged but can resume later

### Option 3: Create Snapshot (Save Configuration)
1. Power off the droplet first
2. Click **"Snapshots"** in the left menu
3. Create snapshot (~$0.05/GB/month)
4. Destroy the droplet
5. Recreate from snapshot when needed

## Best Practices

1. **Always destroy droplets** when testing is complete
2. **Set up billing alerts** in DigitalOcean settings
3. **Use SSH keys** instead of passwords for security
4. **Test during off-peak hours** for more consistent results
5. **Document your test results** with timestamps and conditions

## Troubleshooting

### Can't connect via SSH?
- Check firewall isn't blocking port 22
- Verify IP address is correct
- Try password authentication if SSH key fails

### Python installation issues?
```bash
# Alternative Python installation
sudo apt install python3.10 python3.10-venv python3.10-dev -y
```

### Performance seems slow?
- Check if you're in the correct region (NYC)
- Verify no firewall/proxy interference
- Test at different times of day

## Next Steps

1. Run baseline tests to establish normal response times
2. Test under various load conditions
3. Compare results with tests from other regions
4. Monitor your Railway app's performance metrics simultaneously
5. Adjust your webhook implementation based on findings

Remember to destroy your droplet when testing is complete to avoid unnecessary charges!