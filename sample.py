# project1/conftest.py
import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project1.settings')

if not settings.configured:
    django.setup()
