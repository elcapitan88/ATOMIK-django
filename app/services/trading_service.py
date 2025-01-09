from app.models.subscription import SubscriptionTier

def check_broker_connection_limit(user: User) -> bool:
    """Check if user can add more broker connections"""
    connection_limits = {
        SubscriptionTier.STARTED: 1,
        SubscriptionTier.PLUS: 5,
        SubscriptionTier.PRO: float('inf'),
        SubscriptionTier.LIFETIME: float('inf')
    }

    current_connections = len(user.broker_connections)
    limit = connection_limits.get(user.subscription.tier, 0)
    return current_connections < limit