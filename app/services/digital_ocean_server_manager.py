# app/services/digital_ocean_server_manager.py
import os
import json
import logging
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

import httpx
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.broker import BrokerAccount, BrokerCredentials
from app.core.config import settings

logger = logging.getLogger(__name__)

class DigitalOceanServerManager:
    """
    Service for provisioning and managing IBEam servers on Digital Ocean.
    
    This service creates and manages Digital Ocean droplets that run IBEam,
    allowing users to connect to Interactive Brokers.
    """
    
    def __init__(self):
        """Initialize the Digital Ocean Server Manager."""
        self.api_key = settings.DIGITAL_OCEAN_API_KEY
        self.api_url = "https://api.digitalocean.com/v2"
        self.region = settings.DIGITAL_OCEAN_REGION or "nyc1"
        self.size = settings.DIGITAL_OCEAN_SIZE or "s-1vcpu-1gb"
        self.image = settings.DIGITAL_OCEAN_IMAGE_ID 
        
        # Headers for API requests
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Provisioning status cache to reduce API calls
        self.provisioning_status_cache = {}
        
        # Initialize the HTTP client
        self.client = httpx.AsyncClient(timeout=60.0)  # 60-second timeout for DO API calls
        
        logger.info(f"Digital Ocean Server Manager initialized with region: {self.region}, size: {self.size}")
    
    async def provision_server(
        self,
        db: Session,
        user: User,
        ib_username: str,
        ib_password: str,
        environment: str = "paper"
    ) -> Dict[str, Any]:
        """
        Provision a new IBEam server on Digital Ocean.
        
        Args:
            db: Database session
            user: User requesting the server
            ib_username: Interactive Brokers username
            ib_password: Interactive Brokers password
            environment: "demo", "live", or "paper"
            
        Returns:
            Dict containing server information including account_id and service_id
        """
        try:
            # Count existing servers for this user to create a sequential index
            existing_count = db.query(BrokerAccount).filter(
                BrokerAccount.user_id == user.id,
                BrokerAccount.broker_id == "interactivebrokers",
                BrokerAccount.is_active == True
            ).count()
            
            # Create a meaningful, identifiable name:
            # Format: username-ib-environment-index
            # Example: johndoe-ib-demo-1
            
            # Sanitize username first (remove any invalid chars)
            import re
            sanitized_username = re.sub(r'[^a-zA-Z0-9]', '', user.username or '')
            
            # If username is empty or too short, use part of email instead
            if len(sanitized_username) < 3 and '@' in user.email:
                sanitized_username = re.sub(r'[^a-zA-Z0-9]', '', user.email.split('@')[0])
                
            # Ensure we have something valid
            if not sanitized_username:
                sanitized_username = f"user{user.id}"
                
            # Create the droplet name
            droplet_name = f"{sanitized_username}-ib-{environment}-{existing_count+1}"
            
            # Trim if too long (Digital Ocean has a max length)
            if len(droplet_name) > 253:
                droplet_name = droplet_name[:253]
            
            logger.info(f"Creating Digital Ocean droplet with name: {droplet_name} for user: {user.email}")
            
            # Create user data script to update credentials
            user_data = self._generate_user_data(
                ib_username=ib_username,
                ib_password=ib_password,
                environment=environment
            )
            
            # Prepare tags for the droplet
            tags = ["ibeam", "api-deployed"]
            
            # Create the droplet
            droplet_data = {
                "name": droplet_name,
                "region": self.region,
                "size": self.size,
                "image": self.image,
                "ssh_keys": [],
                "backups": False,
                "ipv6": False,
                "user_data": user_data,
                "tags": tags,
                "monitoring": True,
            }
            
            response = await self.client.post(
                f"{self.api_url}/droplets",
                headers=self.headers,
                json=droplet_data
            )
            
            # Raise exception for non-2xx responses
            response.raise_for_status()
            droplet = response.json()["droplet"]
            droplet_id = droplet["id"]
            
            logger.info(f"Digital Ocean droplet created successfully: {droplet_id}")
            
            # Create an account ID that will be used to identify this connection
            account_id = f"ib-{environment}-{uuid.uuid4().hex[:8]}"
            
            # Create the broker account record
            broker_account = BrokerAccount(
                user_id=user.id,
                broker_id="interactivebrokers",
                account_id=account_id,
                name=f"Interactive Brokers {environment.capitalize()}",
                nickname=f"IB {environment.capitalize()}",
                environment=environment,
                is_active=True,
                status="provisioning",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(broker_account)
            db.flush()  # Get broker_account.id without committing
            
            # Store server details and credentials
            service_data = {
                "droplet_id": droplet_id,
                "droplet_name": droplet_name,
                "status": "provisioning",
                "environment": environment,
                "region": self.region,
                "created_at": datetime.utcnow().isoformat(),
                "last_status_check": datetime.utcnow().isoformat()
            }
            
            # Create the broker credentials record
            broker_credentials = BrokerCredentials(
                broker_id="interactivebrokers",
                account_id=broker_account.id,
                credential_type="digital_ocean_service",
                is_valid=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=30),
                
                # Store in custom_data (for backward compatibility)
                custom_data=json.dumps(service_data),
                
                # Also store in dedicated fields
                do_droplet_id=droplet_id,
                do_droplet_name=droplet_name,
                do_server_status="provisioning",
                do_region=self.region,
                do_last_status_check=datetime.utcnow()
            )
            
            db.add(broker_credentials)
            db.commit()
            
            # Add to monitoring cache
            self.provisioning_status_cache[droplet_id] = {
                "status": "provisioning",
                "last_check": datetime.utcnow(),
                "account_id": account_id,
                "ip_address": None
            }
            
            logger.info(f"Server provisioning initiated for user {user.id}, account {account_id}")
            
            return {
                "account_id": account_id,
                "service_id": droplet_id,
                "status": "provisioning",
                "message": "Server provisioning initiated. This process may take a few minutes."
            }
        
        except httpx.HTTPError as e:
            logger.error(f"HTTP error during server provisioning: {str(e)}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            raise Exception(f"Failed to provision server: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error creating Digital Ocean droplet: {str(e)}")
            # Rollback DB changes if any were made
            db.rollback()
            raise Exception(f"Failed to provision server: {str(e)}")
    
    async def get_server_status(self, droplet_id: int) -> Dict[str, Any]:
        """
        Get the status of a Digital Ocean droplet.
        
        Args:
            droplet_id: The ID of the Digital Ocean droplet
            
        Returns:
            Dict containing status information
        """
        try:
            # Check if we've queried this recently (within 10 seconds)
            cache_entry = self.provisioning_status_cache.get(droplet_id)
            if cache_entry and (datetime.utcnow() - cache_entry["last_check"]).total_seconds() < 10:
                return {
                    "status": cache_entry["status"],
                    "ip_address": cache_entry.get("ip_address"),
                    "last_updated": cache_entry["last_check"].isoformat()
                }
            
            # Query Digital Ocean API for droplet status
            response = await self.client.get(
                f"{self.api_url}/droplets/{droplet_id}",
                headers=self.headers
            )
            
            # Handle non-2xx responses
            if response.status_code == 404:
                logger.warning(f"Droplet {droplet_id} not found")
                return {"status": "deleted", "message": "Server not found"}
            
            response.raise_for_status()
            droplet_data = response.json()["droplet"]
            
            # Extract status
            do_status = droplet_data["status"]
            
            # Translate DO status to our status format
            status_mapping = {
                "new": "provisioning",
                "active": "running",
                "off": "stopped",
                "archive": "suspended"
            }
            status = status_mapping.get(do_status, do_status)
            
            # Get IP address if available
            ip_address = None
            if "networks" in droplet_data and "v4" in droplet_data["networks"]:
                for network in droplet_data["networks"]["v4"]:
                    if network["type"] == "public":
                        ip_address = network["ip_address"]
                        break
            
            # For running servers, check if IBEam is actually ready by pinging the service
            if status == "running" and ip_address:
                is_running = await self._check_ibearmy_running(ip_address)
                if not is_running:
                    status = "initializing"  # Droplet is running but IBEam is not yet ready
            
            # Update cache
            self.provisioning_status_cache[droplet_id] = {
                "status": status,
                "last_check": datetime.utcnow(),
                "ip_address": ip_address
            }
            
            return {
                "status": status,
                "ip_address": ip_address,
                "last_updated": datetime.utcnow().isoformat(),
                "droplet_status": do_status
            }
        
        except httpx.HTTPError as e:
            logger.error(f"HTTP error getting droplet status: {str(e)}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return {"status": "error", "message": f"HTTP error: {str(e)}"}
        
        except Exception as e:
            logger.error(f"Error getting droplet status: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    async def start_server(self, droplet_id: int) -> bool:
        """
        Power on a Digital Ocean droplet.
        
        Args:
            droplet_id: The ID of the Digital Ocean droplet
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Starting Digital Ocean droplet: {droplet_id}")
            
            # Use the power_on action
            response = await self.client.post(
                f"{self.api_url}/droplets/{droplet_id}/actions",
                headers=self.headers,
                json={"type": "power_on"}
            )
            
            response.raise_for_status()
            
            # Update status in cache
            if droplet_id in self.provisioning_status_cache:
                self.provisioning_status_cache[droplet_id]["status"] = "starting"
                self.provisioning_status_cache[droplet_id]["last_check"] = datetime.utcnow()
            
            return True
        
        except Exception as e:
            logger.error(f"Error starting droplet {droplet_id}: {str(e)}")
            return False
    
    async def stop_server(self, droplet_id: int) -> bool:
        """
        Power off a Digital Ocean droplet.
        
        Args:
            droplet_id: The ID of the Digital Ocean droplet
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Stopping Digital Ocean droplet: {droplet_id}")
            
            # Use the power_off action (graceful shutdown)
            response = await self.client.post(
                f"{self.api_url}/droplets/{droplet_id}/actions",
                headers=self.headers,
                json={"type": "power_off"}
            )
            
            response.raise_for_status()
            
            # Update status in cache
            if droplet_id in self.provisioning_status_cache:
                self.provisioning_status_cache[droplet_id]["status"] = "stopping"
                self.provisioning_status_cache[droplet_id]["last_check"] = datetime.utcnow()
            
            return True
        
        except Exception as e:
            logger.error(f"Error stopping droplet {droplet_id}: {str(e)}")
            return False
    
    async def restart_server(self, droplet_id: int) -> bool:
        """
        Restart a Digital Ocean droplet.
        
        Args:
            droplet_id: The ID of the Digital Ocean droplet
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Restarting Digital Ocean droplet: {droplet_id}")
            
            # Use the reboot action
            response = await self.client.post(
                f"{self.api_url}/droplets/{droplet_id}/actions",
                headers=self.headers,
                json={"type": "reboot"}
            )
            
            response.raise_for_status()
            
            # Update status in cache
            if droplet_id in self.provisioning_status_cache:
                self.provisioning_status_cache[droplet_id]["status"] = "restarting"
                self.provisioning_status_cache[droplet_id]["last_check"] = datetime.utcnow()
            
            return True
        
        except Exception as e:
            logger.error(f"Error restarting droplet {droplet_id}: {str(e)}")
            return False
    
    async def delete_server(self, droplet_id: int) -> bool:
        """
        Delete a Digital Ocean droplet.
        
        Args:
            droplet_id: The ID of the Digital Ocean droplet
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Deleting Digital Ocean droplet: {droplet_id}")
            
            # Delete the droplet
            response = await self.client.delete(
                f"{self.api_url}/droplets/{droplet_id}",
                headers=self.headers
            )
            
            # 204 No Content is the success response for deletion
            if response.status_code in (204, 404):  # 404 is also ok - already deleted
                logger.info(f"Droplet {droplet_id} deleted successfully")
                
                # Remove from cache
                if droplet_id in self.provisioning_status_cache:
                    del self.provisioning_status_cache[droplet_id]
                
                return True
            
            logger.error(f"Unexpected response when deleting droplet: {response.status_code} - {response.text}")
            return False
        
        except Exception as e:
            logger.error(f"Error deleting droplet {droplet_id}: {str(e)}")
            return False
    
    async def monitor_server_provisioning(
        self,
        db_session: Session,
        account_id: str,
        droplet_id: int
    ) -> None:
        """
        Monitor the provisioning process of a server.
        
        This method is typically called as a background task.
        
        Args:
            db_session: Database session
            account_id: The broker account ID
            droplet_id: The Digital Ocean droplet ID
        """
        logger.info(f"Starting monitoring for droplet {droplet_id}, account {account_id}")
        
        # Number of times to check status (with wait_time interval)
        max_checks = 30
        wait_time = 20  # seconds between checks
        
        try:
            for attempt in range(max_checks):
                # Get the broker account
                broker_account = db_session.query(BrokerAccount).filter(
                    BrokerAccount.account_id == account_id,
                    BrokerAccount.is_active == True
                ).first()
                
                if not broker_account:
                    logger.warning(f"Broker account {account_id} not found or inactive. Stopping monitoring.")
                    return
                
                # Check droplet status
                status_info = await self.get_server_status(droplet_id)
                status = status_info.get("status", "unknown")
                ip_address = status_info.get("ip_address")
                
                # Update credentials with current status
                if broker_account.credentials:
                    try:
                        # 1. Update custom_data (preserving backward compatibility)
                        if broker_account.credentials.custom_data:
                            service_data = json.loads(broker_account.credentials.custom_data)
                            
                            # Update status if changed
                            if service_data.get("status") != status:
                                service_data["status"] = status
                                service_data["last_status_check"] = datetime.utcnow().isoformat()
                                
                                # Add IP address if available
                                if ip_address:
                                    service_data["ip_address"] = ip_address
                                
                                # Update custom_data
                                broker_account.credentials.custom_data = json.dumps(service_data)
                        
                        # 2. Update dedicated columns
                        broker_account.credentials.do_server_status = status
                        broker_account.credentials.do_last_status_check = datetime.utcnow()
                        
                        if ip_address:
                            broker_account.credentials.do_ip_address = ip_address
                        
                        # Update the broker account status
                        broker_account.status = status
                        
                        # Update timestamps
                        broker_account.credentials.updated_at = datetime.utcnow()
                        broker_account.updated_at = datetime.utcnow()
                        
                        db_session.commit()
                        logger.info(f"Updated status for droplet {droplet_id} to {status}")
                        
                    except Exception as e:
                        logger.error(f"Error updating server status: {str(e)}")
                        db_session.rollback()
                
                # If server is running, check IBeam authentication and fetch account info
                if status == "running" and ip_address:
                    # Check if we haven't already fetched IB account info
                    service_data = json.loads(broker_account.credentials.custom_data) if broker_account.credentials.custom_data else {}
                    if not service_data.get("ib_account_id"):
                        logger.info(f"Server {droplet_id} is running, checking IBeam authentication and fetching account info")
                        await self._check_ibearmy_running(ip_address, broker_account, db_session)
                
                # Break the loop if server is running or in an error state
                if status in ("running", "error", "deleted"):
                    logger.info(f"Server {droplet_id} reached final state: {status}")
                    break
                
                # Wait before checking again
                await asyncio.sleep(wait_time)
            
            logger.info(f"Monitoring completed for droplet {droplet_id}, final status: {status}")
        
        except Exception as e:
            logger.error(f"Error in server monitoring: {str(e)}")
            # Try to update account status to error
            try:
                broker_account = db_session.query(BrokerAccount).filter(
                    BrokerAccount.account_id == account_id,
                    BrokerAccount.is_active == True
                ).first()
                
                if broker_account:
                    broker_account.status = "error"
                    broker_account.error_message = str(e)
                    broker_account.updated_at = datetime.utcnow()
                    
                    if broker_account.credentials:
                        # Update custom_data
                        if broker_account.credentials.custom_data:
                            service_data = json.loads(broker_account.credentials.custom_data)
                            service_data["status"] = "error"
                            service_data["error"] = str(e)
                            broker_account.credentials.custom_data = json.dumps(service_data)
                        
                        # Update dedicated columns
                        broker_account.credentials.do_server_status = "error"
                        broker_account.credentials.updated_at = datetime.utcnow()
                    
                    db_session.commit()
            except Exception as db_error:
                logger.error(f"Error updating account status: {str(db_error)}")
                db_session.rollback()
    
    async def _check_ibearmy_running(self, ip_address: str, broker_account=None, db_session=None) -> bool:
        """Check if the IBEam service is running on the droplet and fetch account info if authenticated."""
        try:
            # Create a custom httpx client that doesn't verify SSL certificates
            # This is safe because we're only connecting to our own internal services
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                url = f"https://{ip_address}:5000/v1/api/tickle"
                response = await client.get(url)
                
                if response.status_code == 200:
                    response_data = response.json()
                    # Look for authentication status in the response
                    if response_data.get("iserver", {}).get("authStatus", {}).get("authenticated") is True:
                        logger.info(f"IBEam service running at {ip_address}: authenticated=true")
                        
                        # Fetch and store real IB account information
                        if broker_account and db_session:
                            await self._fetch_and_store_ib_account_info(ip_address, broker_account, db_session, client)
                        
                        return True
                    
                logger.warning(f"IBEam service at {ip_address} responded but not authenticated")
                return False
        except Exception as e:
            logger.debug(f"IBEam service check failed at {ip_address}: {str(e)}")
            return False
    
    async def _fetch_and_store_ib_account_info(self, ip_address: str, broker_account, db_session, client):
        """Fetch real IB account information and store it in custom_data."""
        try:
            # Call IBeam's /portfolio/accounts endpoint to get real account info
            portfolio_url = f"https://{ip_address}:5000/v1/api/portfolio/accounts"
            portfolio_response = await client.get(portfolio_url)
            
            if portfolio_response.status_code == 200:
                ib_accounts = portfolio_response.json()
                logger.info(f"Retrieved IB accounts from {ip_address}: {len(ib_accounts)} accounts found")
                
                if ib_accounts and len(ib_accounts) > 0:
                    # Get the primary account (first one)
                    primary_account = ib_accounts[0]
                    real_ib_account_id = primary_account.get("accountId") or primary_account.get("id")
                    
                    if real_ib_account_id:
                        # Update custom_data with real IB account information
                        if broker_account.credentials and broker_account.credentials.custom_data:
                            try:
                                service_data = json.loads(broker_account.credentials.custom_data)
                                
                                # Add IB account information
                                service_data["ib_account_id"] = real_ib_account_id
                                service_data["ib_accounts"] = ib_accounts
                                service_data["ib_account_fetched_at"] = datetime.utcnow().isoformat()
                                
                                # Update the custom_data
                                broker_account.credentials.custom_data = json.dumps(service_data)
                                broker_account.credentials.updated_at = datetime.utcnow()
                                
                                # Commit the changes
                                db_session.commit()
                                
                                logger.info(f"Successfully stored real IB account ID: {real_ib_account_id} for account {broker_account.account_id}")
                                
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse custom_data JSON: {e}")
                            except Exception as e:
                                logger.error(f"Failed to update custom_data with IB account info: {e}")
                                db_session.rollback()
                        else:
                            logger.warning("No credentials or custom_data found for broker account")
                    else:
                        logger.warning("No accountId found in IB portfolio accounts response")
                else:
                    logger.warning("No IB accounts returned from portfolio/accounts endpoint")
            else:
                logger.warning(f"Failed to fetch IB accounts: HTTP {portfolio_response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching IB account information from {ip_address}: {str(e)}")
    
    def _generate_user_data(
        self,
        ib_username: str,
        ib_password: str,
        environment: str = "paper"
    ) -> str:
        """
        Generate user data script for configuring IBeam credentials.
        
        Args:
            ib_username: Interactive Brokers username
            ib_password: Interactive Brokers password
            environment: Trading environment (demo/paper/live)
            
        Returns:
            str: User data script
        """
        # Determine if paper trading should be enabled
        use_paper = "true" if environment == "paper" else "false"
        
        # Create a bash script to update credentials and start IBeam
        user_data = f"""#!/bin/bash
# Update IBeam credentials
sed -i "s/IBEAM_ACCOUNT=.*/IBEAM_ACCOUNT={ib_username}/" /root/ibeam_files/env.list
sed -i "s/IBEAM_PASSWORD=.*/IBEAM_PASSWORD={ib_password}/" /root/ibeam_files/env.list

# Set paper trading mode
echo "IBEAM_USE_PAPER_ACCOUNT={use_paper}" >> /root/ibeam_files/env.list

# Start IBeam
. /root/starter.sh
"""
        return user_data
    
    async def cleanup(self):
        """Close resources when shutting down"""
        await self.client.aclose()


# Create singleton instance
digital_ocean_server_manager = DigitalOceanServerManager()

# Export the instance
__all__ = ["digital_ocean_server_manager"]