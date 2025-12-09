import os
import sys
from pathlib import Path
import pytest

# Map project names to their test settings file names
PROJECT_TEST_SETTINGS = {
    'aisc_ap04': 'testing',      # uses settings.testing
    'aisc_ap04_v2': 'test',      # uses settings.test
}

# Map environment names to settings file names per project
PROJECT_ENV_SETTINGS = {
    'aisc_ap04': {
        'test': 'testing',
        'testing': 'testing',
        'dev': 'dev',
        'prod': 'prod',
    },
    'aisc_ap04_v2': {
        'test': 'test',
        'testing': 'test',
        'dev': 'dev',
        'prod': 'prod',
    },
}


def get_project_from_path(path, rootdir):
    """
    Determine which project a test path belongs to
    """
    path = Path(path).resolve()
    
    # Walk up to find which project directory we're in
    for parent in [path] + list(path.parents):
        if parent.parent == rootdir:
            project_name = parent.name
            # Check if this is one of our known projects
            if project_name in PROJECT_TEST_SETTINGS:
                return project_name
            # Also check if settings directory exists
            settings_dir = parent / 'settings'
            if settings_dir.exists() and settings_dir.is_dir():
                return project_name
    
    return None


def get_settings_module(project_name, environment='test'):
    """
    Get the correct settings module for a project and environment
    """
    if project_name in PROJECT_ENV_SETTINGS:
        settings_file = PROJECT_ENV_SETTINGS[project_name].get(
            environment,
            PROJECT_TEST_SETTINGS.get(project_name, 'test')
        )
    else:
        # Fallback for unknown projects
        settings_file = environment
    
    return f'{project_name}.settings.{settings_file}'


def pytest_configure(config):
    """
    Automatically detect and set Django settings based on test collection.
    Handles different naming conventions (testing vs test) per project.
    """
    # Only set if not already configured
    if 'DJANGO_SETTINGS_MODULE' in os.environ:
        import django
        if not django.apps.apps.ready:
            django.setup()
        return
    
    # Get the root directory
    rootdir = Path(config.rootdir)
    
    # Determine which environment to use
    # Priority: DJANGO_SETTINGS_MODULE > DJANGO_ENV > default to 'test'
    environment = os.environ.get('DJANGO_ENV', 'test')
    
    # Try to determine settings from collected test paths
    test_paths = config.args if config.args else []
    
    settings_module = None
    detected_project = None
    
    for path_str in test_paths:
        project_name = get_project_from_path(path_str, rootdir)
        
        if project_name:
            detected_project = project_name
            settings_module = get_settings_module(project_name, environment)
            break
    
    # Fallback to default project if no test path specified
    if not settings_module:
        # Try to find first available project
        default_projects = ['aisc_ap04', 'aisc_ap04_v2']
        
        for project_name in default_projects:
            project_dir = rootdir / project_name
            if project_dir.exists() and (project_dir / 'settings').exists():
                detected_project = project_name
                settings_module = get_settings_module(project_name, environment)
                break
        
        # Ultimate fallback
        if not settings_module:
            settings_module = 'aisc_ap04.settings.testing'
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)
    
    # Print for visibility during test runs
    print(f"\n{'='*60}")
    print(f"Detected project: {detected_project or 'default'}")
    print(f"Using Django settings: {settings_module}")
    print(f"{'='*60}\n")
    
    # Initialize Django
    import django
    django.setup()


def pytest_collection_modifyitems(session, config, items):
    """
    Add markers based on which project the test belongs to
    """
    rootdir = Path(config.rootdir)
    
    for item in items:
        test_path = Path(item.fspath)
        project_name = get_project_from_path(test_path, rootdir)
        
        if project_name:
            # Add project-specific marker
            marker_name = project_name.replace('-', '_')
            item.add_marker(pytest.mark.__getattr__(marker_name))


-------------

import os
import pytest

@pytest.fixture(scope='session', autouse=True)
def ensure_aisc_ap04_settings():
    """Ensure aisc_ap04 settings are used for tests in this directory"""
    current_settings = os.environ.get('DJANGO_SETTINGS_MODULE', '')
    
    # Only override if we're not already using aisc_ap04 settings
    if not current_settings.startswith('aisc_ap04.settings.'):
        environment = os.environ.get('DJANGO_ENV', 'test')
        
        # Map environment to correct settings file for aisc_ap04
        settings_map = {
            'test': 'testing',
            'testing': 'testing',
            'dev': 'dev',
            'prod': 'prod',
        }
        settings_file = settings_map.get(environment, 'testing')
        
        os.environ['DJANGO_SETTINGS_MODULE'] = f'aisc_ap04.settings.{settings_file}'
        
        import django
        if django.apps.apps.ready:
            # Reload settings if Django was already configured
            from django.conf import settings
            settings._wrapped = None
        django.setup()


@pytest.fixture
def aisc_ap04_client(db):
    """Django test client configured for aisc_ap04"""
    from django.test import Client
    return Client()


------------------
import os
import pytest

@pytest.fixture(scope='session', autouse=True)
def ensure_aisc_ap04_v2_settings():
    """Ensure aisc_ap04_v2 settings are used for tests in this directory"""
    current_settings = os.environ.get('DJANGO_SETTINGS_MODULE', '')
    
    # Only override if we're not already using aisc_ap04_v2 settings
    if not current_settings.startswith('aisc_ap04_v2.settings.'):
        environment = os.environ.get('DJANGO_ENV', 'test')
        
        # Map environment to correct settings file for aisc_ap04_v2
        settings_map = {
            'test': 'test',
            'testing': 'test',
            'dev': 'dev',
            'prod': 'prod',
        }
        settings_file = settings_map.get(environment, 'test')
        
        os.environ['DJANGO_SETTINGS_MODULE'] = f'aisc_ap04_v2.settings.{settings_file}'
        
        import django
        if django.apps.apps.ready:
            # Reload settings if Django was already configured
            from django.conf import settings
            settings._wrapped = None
        django.setup()


@pytest.fixture
def aisc_ap04_v2_client(db):
    """Django test client configured for aisc_ap04_v2"""
    from django.test import Client
    return Client()



--------
[pytest]
DJANGO_SETTINGS_MODULE = 
python_files = test_*.py *_test.py tests.py
python_classes = Test*
python_functions = test_*
testpaths = aisc_ap04 aisc_ap04_v2
addopts = 
    --verbose
    --strict-markers
    --tb=short
    -p no:warnings
markers =
    aisc_ap04: marks tests as aisc_ap04 tests
    aisc_ap04_v2: marks tests as aisc_ap04_v2 tests
    slow: marks tests as slow
    integration: marks tests as integration tests
