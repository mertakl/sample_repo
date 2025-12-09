import os
import sys
from pathlib import Path
import pytest

def pytest_configure(config):
    """
    Automatically detect and set Django settings based on test collection.
    Uses test.py settings by default for pytest runs.
    """
    # Only set if not already configured
    if 'DJANGO_SETTINGS_MODULE' in os.environ:
        import django
        if not django.apps.apps.ready:
            django.setup()
        return
    
    # Get the root directory
    rootdir = Path(config.rootdir)
    
    # Determine which environment to use (default to 'test' for pytest)
    environment = os.environ.get('DJANGO_ENV', 'test')
    
    # Try to determine settings from collected test paths
    test_paths = config.args if config.args else []
    
    settings_module = None
    for path_str in test_paths:
        path = Path(path_str).resolve()
        
        # Walk up to find which project directory we're in
        for parent in [path] + list(path.parents):
            if parent.parent == rootdir:
                # Check if this directory has a settings folder
                settings_dir = parent / 'settings'
                if settings_dir.exists() and settings_dir.is_dir():
                    # Check if the environment-specific settings file exists
                    settings_file = settings_dir / f'{environment}.py'
                    if settings_file.exists():
                        settings_module = f'{parent.name}.settings.{environment}'
                        break
                
                # Fallback: check for single settings.py file
                settings_file = parent / 'settings.py'
                if settings_file.exists():
                    settings_module = f'{parent.name}.settings'
                    break
        
        if settings_module:
            break
    
    # Fallback to default project
    if not settings_module:
        # Try to find first available project with settings
        for item in rootdir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                settings_dir = item / 'settings'
                if settings_dir.exists():
                    settings_module = f'{item.name}.settings.{environment}'
                    break
                elif (item / 'settings.py').exists():
                    settings_module = f'{item.name}.settings'
                    break
        
        # Ultimate fallback
        if not settings_module:
            settings_module = 'project1.settings.test'
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)
    print(f"Using Django settings: {settings_module}")
    
    # Initialize Django
    import django
    django.setup()


def pytest_collection_modifyitems(session, config, items):
    """
    Add markers based on which project the test belongs to
    """
    for item in items:
        test_path = Path(item.fspath)
        
        # Add project-specific markers
        for part in test_path.parts:
            if part.startswith('project'):
                item.add_marker(pytest.mark.__getattr__(part))




import os
import pytest

@pytest.fixture(scope='session', autouse=True)
def ensure_project1_settings():
    """Ensure project1 settings are used for tests in this directory"""
    current_settings = os.environ.get('DJANGO_SETTINGS_MODULE', '')
    
    # Only override if we're in project1 and settings aren't set
    if not current_settings or not current_settings.startswith('project1.'):
        environment = os.environ.get('DJANGO_ENV', 'test')
        os.environ['DJANGO_SETTINGS_MODULE'] = f'project1.settings.{environment}'
        
        import django
        if django.apps.apps.ready:
            # Need to reload if Django was already setup with wrong settings
            from django.conf import settings
            settings._wrapped = None
        django.setup()


@pytest.fixture
def project1_specific_fixture():
    """Project1-specific fixtures can go here"""
    pass



import os
import pytest

@pytest.fixture(scope='session', autouse=True)
def ensure_project2_settings():
    """Ensure project2 settings are used for tests in this directory"""
    current_settings = os.environ.get('DJANGO_SETTINGS_MODULE', '')
    
    if not current_settings or not current_settings.startswith('project2.'):
        environment = os.environ.get('DJANGO_ENV', 'test')
        os.environ['DJANGO_SETTINGS_MODULE'] = f'project2.settings.{environment}'
        
        import django
        if django.apps.apps.ready:
            from django.conf import settings
            settings._wrapped = None
        django.setup()


@pytest.fixture
def project2_specific_fixture():
    """Project2-specific fixtures can go here"""
    pass
