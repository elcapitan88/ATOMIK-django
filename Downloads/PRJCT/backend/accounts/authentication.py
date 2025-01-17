from rest_framework_simplejwt.tokens import RefreshToken
from datetime import timedelta
from django.conf import settings

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

def create_jwt_token(user):
    token = get_tokens_for_user(user)
    return token