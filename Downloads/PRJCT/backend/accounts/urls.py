from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('verify/', views.verify_token, name='verify'), 
    path('refresh/', views.refresh_token_view, name='refresh_token'),
]