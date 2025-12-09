import os
import sys
from pathlib import Path
import pytest

def pytest_configure(config):
    """
    Automatically detect and set Django settings based on test collection
    """
    # Only set if not already configured
    if 'DJANGO_SETTINGS_MODULE' in os.environ:
        return
    
    # Get the root directory
    rootdir = Path(config.rootdir)
    
    # Try to determine settings from collected test paths
    test_paths = config.args if config.args else []
    
    settings_module = None
    for path_str in test_paths:
        path = Path(path_str)
        
        # Walk up to find which project directory we're in
        for parent in [path] + list(path.parents):
            if parent.parent == rootdir:
                # Check if this directory has a settings.py
                settings_file = parent / 'settings.py'
                if settings_file.exists():
                    settings_module = f'{parent.name}.settings'
                    break
        
        if settings_module:
            break
    
    # Fallback to default
    if not settings_module:
        settings_module = 'project1.settings'
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)
    
    # Initialize Django
    import django
    django.setup()


def pytest_collection_modifyitems(session, config, items):
    """
    Group tests by their settings module to avoid conflicts
    """
    # Optional: Add markers based on which project the test belongs to
    for item in items:
        test_path = Path(item.fspath)
        
        if 'project1' in test_path.parts:
            item.add_marker(pytest.mark.project1)
        elif 'project2' in test_path.parts:
            item.add_marker(pytest.mark.project2)
