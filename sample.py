import os

def pytest_pycollect_makeitem(collector, name, obj):
    # Configure Django settings early
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project_a.settings")
