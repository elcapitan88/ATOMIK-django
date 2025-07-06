import httpx
from typing import Optional, Dict, Any
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class IBProxyClient:
    """Client for communicating with IBeam instances through our DO proxy"""
    
    def __init__(self):
        self.proxy_url = settings.IB_PROXY_URL
        self.api_key = settings.IB_PROXY_API_KEY
        
        if not self.proxy_url or not self.api_key:
            logger.warning("IB_PROXY_URL and IB_PROXY_API_KEY not configured. Proxy client will not work.")
            self.proxy_url = None
            self.api_key = None
    
    async def call_ibeam(
        self,
        droplet_ip: str,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0
    ) -> Dict[str, Any]:
        """Route IBeam API calls through our DO proxy"""
        if not self.proxy_url or not self.api_key:
            raise ValueError("Proxy not configured. Set IB_PROXY_URL and IB_PROXY_API_KEY environment variables.")
            
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.proxy_url}/proxy",
                    headers={"X-API-Key": self.api_key},
                    json={
                        "droplet_ip": droplet_ip,
                        "method": method,
                        "path": path,
                        "headers": headers,
                        "body": body
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                if "data" in result:
                    return result["data"]
                return result
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Proxy HTTP error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Proxy request failed: {str(e)}")
            raise
    
    async def check_health(self, droplet_ip: str) -> bool:
        """Quick health check for IBeam instance"""
        if not self.proxy_url or not self.api_key:
            logger.error("Proxy not configured for health check")
            return False
            
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.proxy_url}/proxy/health/{droplet_ip}",
                    headers={"X-API-Key": self.api_key}
                )
                
                response.raise_for_status()
                data = response.json()
                return data.get("authenticated", False)
                
        except Exception as e:
            logger.error(f"Health check failed for {droplet_ip}: {str(e)}")
            return False

ib_proxy_client = IBProxyClient()