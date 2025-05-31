# app/services/chat_role_service.py
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from ..models.chat import UserChatRole
from ..models.user import User
from ..models.subscription import Subscription
from ..core.subscription_tiers import SubscriptionTier, get_tier_display_name


# Role color mapping based on subscription tiers
ROLE_COLORS = {
    'Admin': '#FF0000',
    'Moderator': '#FFA500',
    'Beta Tester': '#9932CC',  # Purple for beta testers
    'Legacy Free': '#808080',  # For grandfathered free users
    'Starter': '#FFFFFF',      # New display name for Pro tier
    'Pro': '#00C6E0',         # New display name for Elite tier
    'VIP': '#FFD700',         # For special users
}

# Role priority mapping (higher = more important)
ROLE_PRIORITIES = {
    'Admin': 100,
    'Moderator': 90,
    'Beta Tester': 80,
    'VIP': 85,
    'Pro': 70,
    'Starter': 60,
    'Legacy Free': 50,
}


async def assign_default_role_from_subscription(
    db: Session, 
    user_id: int, 
    subscription: Optional[Subscription] = None
) -> UserChatRole:
    """
    Assign a chat role based on user's subscription tier
    
    Args:
        db: Database session
        user_id: User ID to assign role to
        subscription: Optional subscription object (will query if not provided)
    
    Returns:
        UserChatRole: The assigned role
    """
    # Get subscription if not provided
    if not subscription:
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).first()
    
    # Determine role name based on subscription
    if not subscription:
        role_name = 'Legacy Free'
    elif subscription.is_legacy_free:
        role_name = 'Legacy Free'
    else:
        # Use the display name from subscription tiers
        role_name = get_tier_display_name(subscription.tier)
    
    # Remove existing subscription-based roles (keep Admin/Moderator/Beta Tester roles)
    db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name.in_(['Legacy Free', 'Starter', 'Pro', 'VIP']),
            UserChatRole.is_active == True
        )
    ).update({UserChatRole.is_active: False})
    
    # Create new role
    new_role = UserChatRole(
        user_id=user_id,
        role_name=role_name,
        role_color=ROLE_COLORS.get(role_name, '#808080'),
        role_priority=ROLE_PRIORITIES.get(role_name, 50),
        is_active=True
    )
    
    db.add(new_role)
    db.commit()
    db.refresh(new_role)
    
    return new_role


async def assign_admin_role(
    db: Session, 
    user_id: int, 
    assigned_by_id: int
) -> UserChatRole:
    """
    Assign admin role to a user (updates both chat role and app role)
    
    Args:
        db: Database session
        user_id: User to make admin
        assigned_by_id: User who is assigning the role
    
    Returns:
        UserChatRole: The admin role
    """
    from ..models.user import User
    
    # Check if user already has admin role
    existing_admin = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Admin',
            UserChatRole.is_active == True
        )
    ).first()
    
    if existing_admin:
        # Also ensure app_role is set to admin
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.app_role = 'admin'
            db.commit()
        return existing_admin
    
    # Update user's app_role to admin
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.app_role = 'admin'
    
    # Create admin role
    admin_role = UserChatRole(
        user_id=user_id,
        role_name='Admin',
        role_color=ROLE_COLORS['Admin'],
        role_priority=ROLE_PRIORITIES['Admin'],
        assigned_by=assigned_by_id,
        is_active=True
    )
    
    db.add(admin_role)
    db.commit()
    db.refresh(admin_role)
    
    return admin_role


async def assign_moderator_role(
    db: Session, 
    user_id: int, 
    assigned_by_id: int
) -> UserChatRole:
    """
    Assign moderator role to a user (updates both chat role and app role)
    
    Args:
        db: Database session
        user_id: User to make moderator
        assigned_by_id: User who is assigning the role
    
    Returns:
        UserChatRole: The moderator role
    """
    from ..models.user import User
    
    # Check if user already has moderator role
    existing_moderator = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Moderator',
            UserChatRole.is_active == True
        )
    ).first()
    
    if existing_moderator:
        # Also ensure app_role is set to moderator (unless they're admin)
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.app_role != 'admin':
            user.app_role = 'moderator'
            db.commit()
        return existing_moderator
    
    # Update user's app_role to moderator (unless they're admin)
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.app_role != 'admin':
        user.app_role = 'moderator'
    
    # Create moderator role
    moderator_role = UserChatRole(
        user_id=user_id,
        role_name='Moderator',
        role_color=ROLE_COLORS['Moderator'],
        role_priority=ROLE_PRIORITIES['Moderator'],
        assigned_by=assigned_by_id,
        is_active=True
    )
    
    db.add(moderator_role)
    db.commit()
    db.refresh(moderator_role)
    
    return moderator_role


async def assign_vip_role(
    db: Session, 
    user_id: int, 
    assigned_by_id: int
) -> UserChatRole:
    """
    Assign VIP role to a user (for special members)
    
    Args:
        db: Database session
        user_id: User to make VIP
        assigned_by_id: User who is assigning the role
    
    Returns:
        UserChatRole: The VIP role
    """
    # Remove existing VIP role if any
    db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'VIP',
            UserChatRole.is_active == True
        )
    ).update({UserChatRole.is_active: False})
    
    # Create VIP role
    vip_role = UserChatRole(
        user_id=user_id,
        role_name='VIP',
        role_color=ROLE_COLORS['VIP'],
        role_priority=ROLE_PRIORITIES['VIP'],
        assigned_by=assigned_by_id,
        is_active=True
    )
    
    db.add(vip_role)
    db.commit()
    db.refresh(vip_role)
    
    return vip_role


async def remove_admin_role(db: Session, user_id: int) -> bool:
    """Remove admin role from user (updates both chat role and app role)"""
    from ..models.user import User
    
    result = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Admin',
            UserChatRole.is_active == True
        )
    ).update({UserChatRole.is_active: False})
    
    # Check if they have moderator role, otherwise set to None
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.app_role == 'admin':
        moderator_role = db.query(UserChatRole).filter(
            and_(
                UserChatRole.user_id == user_id,
                UserChatRole.role_name == 'Moderator',
                UserChatRole.is_active == True
            )
        ).first()
        
        if moderator_role:
            user.app_role = 'moderator'
        else:
            beta_role = db.query(UserChatRole).filter(
                and_(
                    UserChatRole.user_id == user_id,
                    UserChatRole.role_name == 'Beta Tester',
                    UserChatRole.is_active == True
                )
            ).first()
            user.app_role = 'beta_tester' if beta_role else None
    
    db.commit()
    return result > 0


async def remove_moderator_role(db: Session, user_id: int) -> bool:
    """Remove moderator role from user (updates both chat role and app role)"""
    from ..models.user import User
    
    result = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Moderator',
            UserChatRole.is_active == True
        )
    ).update({UserChatRole.is_active: False})
    
    # Update app_role if currently moderator (but preserve admin)
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.app_role == 'moderator':
        # Check if they have beta tester role
        beta_role = db.query(UserChatRole).filter(
            and_(
                UserChatRole.user_id == user_id,
                UserChatRole.role_name == 'Beta Tester',
                UserChatRole.is_active == True
            )
        ).first()
        user.app_role = 'beta_tester' if beta_role else None
    
    db.commit()
    return result > 0


async def remove_vip_role(db: Session, user_id: int) -> bool:
    """Remove VIP role from user"""
    result = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'VIP',
            UserChatRole.is_active == True
        )
    ).update({UserChatRole.is_active: False})
    
    db.commit()
    return result > 0


async def assign_beta_tester_role(
    db: Session, 
    user_id: int, 
    assigned_by_id: int
) -> UserChatRole:
    """
    Assign beta tester role to a user (updates both chat role and app role)
    
    Args:
        db: Database session
        user_id: User to make beta tester
        assigned_by_id: User who is assigning the role
    
    Returns:
        UserChatRole: The beta tester role
    """
    from ..models.user import User
    
    # Check if user already has beta tester role
    existing_beta = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Beta Tester',
            UserChatRole.is_active == True
        )
    ).first()
    
    if existing_beta:
        # Also ensure app_role is set if not already admin/moderator
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.app_role not in ['admin', 'moderator']:
            user.app_role = 'beta_tester'
            db.commit()
        return existing_beta
    
    # Update user's app_role if not already admin/moderator
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.app_role not in ['admin', 'moderator']:
        user.app_role = 'beta_tester'
    
    # Create beta tester role
    beta_role = UserChatRole(
        user_id=user_id,
        role_name='Beta Tester',
        role_color=ROLE_COLORS['Beta Tester'],
        role_priority=ROLE_PRIORITIES['Beta Tester'],
        assigned_by=assigned_by_id,
        is_active=True
    )
    
    db.add(beta_role)
    db.commit()
    db.refresh(beta_role)
    
    return beta_role


async def remove_beta_tester_role(db: Session, user_id: int) -> bool:
    """Remove beta tester role from user (updates both chat role and app role)"""
    from ..models.user import User
    
    result = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Beta Tester',
            UserChatRole.is_active == True
        )
    ).update({UserChatRole.is_active: False})
    
    # Also remove app_role if it's beta_tester (but preserve admin/moderator)
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.app_role == 'beta_tester':
        user.app_role = None
    
    db.commit()
    return result > 0


async def get_user_roles(db: Session, user_id: int) -> List[UserChatRole]:
    """
    Get all active roles for a user
    
    Args:
        db: Database session
        user_id: User ID
    
    Returns:
        List[UserChatRole]: List of active roles
    """
    return db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.is_active == True
        )
    ).order_by(UserChatRole.role_priority.desc()).all()


async def get_user_primary_role(db: Session, user_id: int) -> Optional[UserChatRole]:
    """
    Get the highest priority role for a user
    
    Args:
        db: Database session
        user_id: User ID
    
    Returns:
        Optional[UserChatRole]: Highest priority role or None
    """
    return db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.is_active == True
        )
    ).order_by(UserChatRole.role_priority.desc()).first()


async def get_user_role_color(db: Session, user_id: int) -> str:
    """
    Get the role color for a user (highest priority role)
    
    Args:
        db: Database session
        user_id: User ID
    
    Returns:
        str: Hex color code
    """
    primary_role = await get_user_primary_role(db, user_id)
    return primary_role.role_color if primary_role else ROLE_COLORS['Legacy Free']


async def is_user_admin(db: Session, user_id: int) -> bool:
    """Check if user has admin role"""
    admin_role = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Admin',
            UserChatRole.is_active == True
        )
    ).first()
    
    return admin_role is not None


async def is_user_moderator(db: Session, user_id: int) -> bool:
    """Check if user has moderator role"""
    moderator_role = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Moderator',
            UserChatRole.is_active == True
        )
    ).first()
    
    return moderator_role is not None


async def is_user_beta_tester(db: Session, user_id: int) -> bool:
    """Check if user has beta tester role"""
    beta_role = db.query(UserChatRole).filter(
        and_(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == 'Beta Tester',
            UserChatRole.is_active == True
        )
    ).first()
    
    return beta_role is not None


async def is_user_staff(db: Session, user_id: int) -> bool:
    """Check if user has admin or moderator role"""
    return await is_user_admin(db, user_id) or await is_user_moderator(db, user_id)


async def sync_user_subscription_role(db: Session, user_id: int) -> UserChatRole:
    """
    Sync user's chat role with their current subscription tier
    This should be called when a user's subscription changes
    
    Args:
        db: Database session
        user_id: User ID to sync
    
    Returns:
        UserChatRole: The updated role
    """
    # Get current subscription
    subscription = db.query(Subscription).filter(
        Subscription.user_id == user_id
    ).first()
    
    return await assign_default_role_from_subscription(db, user_id, subscription)


async def get_all_admins(db: Session) -> List[Dict]:
    """
    Get all users with admin roles
    
    Returns:
        List[Dict]: List of admin users with basic info
    """
    admins = db.query(UserChatRole, User).join(
        User, UserChatRole.user_id == User.id
    ).filter(
        and_(
            UserChatRole.role_name == 'Admin',
            UserChatRole.is_active == True
        )
    ).all()
    
    return [
        {
            "user_id": role.user_id,
            "username": user.username,
            "email": user.email,
            "assigned_at": role.assigned_at,
            "assigned_by": role.assigned_by
        }
        for role, user in admins
    ]


async def get_all_moderators(db: Session) -> List[Dict]:
    """
    Get all users with moderator roles
    
    Returns:
        List[Dict]: List of moderator users with basic info
    """
    moderators = db.query(UserChatRole, User).join(
        User, UserChatRole.user_id == User.id
    ).filter(
        and_(
            UserChatRole.role_name == 'Moderator',
            UserChatRole.is_active == True
        )
    ).all()
    
    return [
        {
            "user_id": role.user_id,
            "username": user.username,
            "email": user.email,
            "assigned_at": role.assigned_at,
            "assigned_by": role.assigned_by
        }
        for role, user in moderators
    ]


async def get_all_beta_testers(db: Session) -> List[Dict]:
    """
    Get all users with beta tester roles
    
    Returns:
        List[Dict]: List of beta tester users with basic info
    """
    beta_testers = db.query(UserChatRole, User).join(
        User, UserChatRole.user_id == User.id
    ).filter(
        and_(
            UserChatRole.role_name == 'Beta Tester',
            UserChatRole.is_active == True
        )
    ).all()
    
    return [
        {
            "user_id": role.user_id,
            "username": user.username,
            "email": user.email,
            "assigned_at": role.assigned_at,
            "assigned_by": role.assigned_by,
            "app_role": user.app_role
        }
        for role, user in beta_testers
    ]


async def sync_existing_beta_testers(db: Session) -> int:
    """
    Sync existing chat beta testers to have app_role = 'beta_tester'
    This helps migrate old beta testers after the app_role system implementation
    
    Returns:
        int: Number of users updated
    """
    from ..models.user import User
    
    # Find all users with active beta tester chat roles but no app_role
    beta_testers = db.query(UserChatRole, User).join(
        User, UserChatRole.user_id == User.id
    ).filter(
        and_(
            UserChatRole.role_name == 'Beta Tester',
            UserChatRole.is_active == True,
            or_(User.app_role.is_(None), User.app_role == '')
        )
    ).all()
    
    updated_count = 0
    for role, user in beta_testers:
        user.app_role = 'beta_tester'
        updated_count += 1
    
    db.commit()
    return updated_count