# Webhook Stress Testing Guide

## 🎯 Purpose
Test the high-frequency trading webhook system to ensure it won't crash under load like before.

## 📋 What We're Testing

### 1. **Memory Stability**
- Monitor for memory leaks that caused worker crashes
- Track memory usage over sustained load
- Detect memory growth patterns

### 2. **Rate Limiting**
- Verify 10 requests/second limit works correctly
- Test burst handling (multiple requests at once)
- Ensure legitimate HFT traffic isn't blocked

### 3. **Concurrency**
- Test multiple simultaneous webhook requests
- Verify distributed locking prevents race conditions
- Check database connection pool stability

### 4. **Performance**
- Measure response times under load
- Test 1-second idempotency TTL
- Monitor system resources (CPU, connections)

## 🚀 Setup Instructions

### 1. **Install Dependencies**
```bash
pip install aiohttp psutil requests
```

### 2. **Create a Test Webhook**
First, get an authentication token and create a webhook:

```bash
# Login and get token (replace with your credentials)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "your@email.com", "password": "yourpassword"}'

# Create test webhook (replace YOUR_TOKEN with the token from login)
curl -X POST http://localhost:8000/api/v1/webhooks/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "HFT Stress Test Webhook", "details": "For stress testing"}'
```

### 3. **Update Configuration**
Edit `stress_test_webhooks.py` and update these variables:

```python
BASE_URL = "http://localhost:8000"  # Your server URL
WEBHOOK_TOKEN = "abc123..."         # Token from webhook creation
WEBHOOK_SECRET = "def456..."        # Secret from webhook creation
```

### 4. **Start Your Server**
Make sure your FastAPI server is running:
```bash
cd fastapi_backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 🧪 Running the Tests

### Option 1: Full Automated Test
```bash
./run_stress_test.sh
```

### Option 2: Manual Testing

**Start Health Monitoring:**
```bash
python monitor_server_health.py --duration 300 --interval 1
```

**In another terminal, run stress tests:**
```bash
python stress_test_webhooks.py
```

## 📊 Test Scenarios

### **Test 1: High-Frequency Trading**
- 100 rapid buy/sell signals
- Tests: Rate limiting, memory usage, response times

### **Test 2: Burst Load**
- 100 identical requests sent simultaneously
- Tests: Idempotency, concurrency handling, system stability

### **Test 3: Sustained Load**
- Continuous requests for 30 seconds
- Tests: Memory leaks, connection pooling, performance degradation

### **Test 4: Memory Leak Detection**
- 1000 requests sent in batches with memory sampling
- Tests: Memory growth patterns, garbage collection

### **Test 5: Rate Limiting**
- 20 requests sent as fast as possible
- Tests: Rate limiting effectiveness (should allow 10, block 10)

## 🚨 What to Watch For

### **Critical Issues**
- **Memory leaks** - Memory increasing > 100MB during test
- **Worker crashes** - Process dying with SIGKILL
- **Rate limiting failures** - Too many requests getting through
- **Response time degradation** - Times > 1000ms

### **Warning Signs**
- CPU usage > 80% sustained
- Response times > 500ms
- Error rates > 5%
- Memory growth > 50MB during sustained load

## 📈 Expected Results

### **Good Performance**
```
✅ Successful Requests: >95%
✅ Avg Response Time: <100ms
✅ Memory Growth: <50MB
✅ Rate Limited: ~50% when testing limits
✅ Zero worker crashes
```

### **Performance Issues**
```
⚠️  Successful Requests: <90%
⚠️  Avg Response Time: >500ms
⚠️  Memory Growth: >100MB
⚠️  Rate Limiting: Not working properly
⚠️  Worker crashes detected
```

## 📄 Results Analysis

After testing, check these files:
- `server_health_report_*.json` - Detailed metrics
- `monitor.log` - Real-time monitoring output

Key metrics to review:
```json
{
  "summary": {
    "max_cpu_percent": 45.2,      // Should be <80%
    "max_memory_mb": 512.3,       // Should be stable
    "avg_response_time_ms": 85.4, // Should be <200ms
    "total_alerts": 0             // Should be 0 or minimal
  }
}
```

## 🔧 Troubleshooting

### **High Memory Usage**
- Check for memory leaks in background tasks
- Verify Redis connections are being closed
- Monitor database connection pool

### **Slow Response Times**
- Check database query performance
- Verify Redis connectivity
- Monitor background task queue

### **Rate Limiting Issues**
- Check Redis connection
- Verify rate limiting logic
- Test fallback to database rate limiting

### **Worker Crashes**
- Monitor memory usage patterns
- Check error logs for exceptions
- Verify graceful shutdown handling

## 🎯 Success Criteria

The system passes stress testing if:

1. **Zero worker crashes** during all tests
2. **Memory growth < 100MB** during sustained load
3. **95%+ success rate** for legitimate requests  
4. **Rate limiting works** (blocks excess requests)
5. **Response times < 200ms** under normal load
6. **No database errors** or connection issues

If any of these fail, we need to investigate and fix before deploying to production.