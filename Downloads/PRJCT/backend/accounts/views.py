from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from datetime import timedelta
import json
import logging
from .models import CustomUser

logger = logging.getLogger(__name__)

@csrf_exempt
def register(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = data.get('username')
            email = data.get('email')
            password = data.get('password')

            # Validate input
            if not all([username, email, password]):
                return JsonResponse({
                    'message': 'Username, email, and password are required'
                }, status=400)

            # Check if user already exists
            if CustomUser.objects.filter(email=email).exists():
                return JsonResponse({
                    'message': 'Email already registered'
                }, status=400)

            # Create new user
            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            # Generate tokens
            refresh = RefreshToken.for_user(user)
            tokens = {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }

            response = JsonResponse({
                'message': 'User registered successfully',
                'user_id': user.id,
                'tokens': tokens
            })

            # Set refresh token in HttpOnly cookie
            response.set_cookie(
                'refresh_token',
                tokens['refresh'],
                httponly=True,
                secure=True,
                samesite='Strict',
                max_age=60 * 60 * 24 * 7  # 7 days
            )

            return response

        except json.JSONDecodeError:
            return JsonResponse({
                'message': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            return JsonResponse({
                'message': 'An unexpected error occurred'
            }, status=500)

    return JsonResponse({
        'message': 'Invalid request method'
    }, status=405)

@csrf_exempt
def login_view(request):
    logger.info("Login view called")  # Debug log
    if request.method == 'POST':
        try:
            logger.info(f"Raw request body: {request.body}")  # Debug log
            data = json.loads(request.body)
            email = data.get('email')
            password = data.get('password')
            
            logger.info(f"Login attempt for email: {email}")  # Debug log
            
            if not email or not password:
                logger.warning("Missing email or password")
                return JsonResponse({
                    'message': 'Email and password are required'
                }, status=400)

            user = authenticate(request, username=email, password=password)
            logger.info(f"Authentication result: {user is not None}")  # Debug log

            if user is not None:
                login(request, user)
                
                # Generate tokens
                refresh = RefreshToken.for_user(user)
                tokens = {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }

                logger.info(f"Successfully logged in user {user.id}")  # Debug log

                response = JsonResponse({
                    'message': 'Login successful',
                    'user_id': user.id,
                    'tokens': tokens
                })

                # Set refresh token cookie
                response.set_cookie(
                    'refresh_token',
                    tokens['refresh'],
                    httponly=True,
                    secure=True,  # Set to False in development if not using HTTPS
                    samesite='Lax',
                    max_age=60 * 60 * 24 * 7  # 7 days
                )

                return response
            else:
                logger.warning(f"Invalid credentials for email: {email}")  # Debug log
                return JsonResponse({
                    'message': 'Invalid credentials'
                }, status=400)

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")  # Debug log
            return JsonResponse({
                'message': 'Invalid JSON format'
            }, status=400)
        except Exception as e:
            logger.error(f"Unexpected error in login: {str(e)}", exc_info=True)  # Debug log
            return JsonResponse({
                'message': 'An unexpected error occurred'
            }, status=500)

    logger.warning(f"Invalid request method: {request.method}")  # Debug log
    return JsonResponse({
        'message': 'Invalid request method'
    }, status=405)

@csrf_exempt
@require_POST
def logout_view(request):
    try:
        # Clear the refresh token cookie
        response = JsonResponse({
            'message': 'Logged out successfully'
        })
        response.delete_cookie('refresh_token')
        
        # Perform Django logout
        logout(request)
        
        return response
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return JsonResponse({
            'message': 'An error occurred during logout'
        }, status=500)

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def verify_token(request):
    """Verify that the current token is valid"""
    return JsonResponse({
        'message': 'Token is valid',
        'user_id': request.user.id
    })

@csrf_exempt
def refresh_token_view(request):
    try:
        refresh_token = request.COOKIES.get('refresh_token')
        if not refresh_token:
            return JsonResponse({
                'message': 'No refresh token provided'
            }, status=400)
        
        refresh = RefreshToken(refresh_token)
        tokens = {
            'access': str(refresh.access_token),
        }
        
        return JsonResponse(tokens)
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        return JsonResponse({
            'message': 'Invalid refresh token'
        }, status=400)