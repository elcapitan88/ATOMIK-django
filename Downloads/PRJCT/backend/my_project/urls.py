# project/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('strategies.urls')),
    path('api/tradovate/', include('strategies.brokers.tradovate.urls', namespace='tradovate')),
]