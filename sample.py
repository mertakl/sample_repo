
import os
import sys
from pathlib import Path
import django
from django.conf import settings


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "django_project1: mark test to use project1 settings"
    )
    config.addinivalue_line(
        "markers", "django_project2: mark test to use project2 settings"
    )


class DjangoProjectManager:
    """Manages Django setup/teardown for different projects."""
    
    def __init__(self):
        self.current_project = None
        self.current_settings = None
    
    def setup_project(self, project_name, settings_module, project_path):
        """Setup Django for a specific project."""
        if self.current_project == project_name:
            return  # Already set up
        
        # Teardown previous project if exists
        if self.current_project:
            self.teardown_project()
        
        # Set up new project
        self.current_project = project_name
        self.current_settings = settings_module
        
        # Add project to path
        if str(project_path) not in sys.path:
            sys.path.insert(0, str(project_path))
        
        # Set Django settings
        os.environ['DJANGO_SETTINGS_MODULE'] = settings_module
        
        # Reset Django setup state
        if settings.configured:
            # Force Django to reload with new settings
            from django.apps import apps
            apps.app_configs.clear()
            apps.all_models.clear()
            apps.ready = False
            settings._wrapped = None
        
        # Setup Django
        django.setup()
    
    def teardown_project(self):
        """Teardown current Django project."""
        if not self.current_project:
            return
        
        from django.test.utils import teardown_databases
        from django.db import connections
        
        # Close all database connections
        for conn in connections.all():
            conn.close()
        
        self.current_project = None
        self.current_settings = None


# Global manager instance
django_manager = DjangoProjectManager()


def pytest_collection_modifyitems(config, items):
    """Organize tests by project and set up Django accordingly."""
    # Group tests by project
    project_groups = {'project1': [], 'project2': [], 'other': []}
    
    for item in items:
        test_path = Path(item.fspath)
        
        if 'project1' in test_path.parts:
            project_groups['project1'].append(item)
        elif 'project2' in test_path.parts:
            project_groups['project2'].append(item)
        else:
            project_groups['other'].append(item)
    
    # Reorder items to group by project (minimizes Django reloads)
    new_items = []
    new_items.extend(project_groups['project1'])
    new_items.extend(project_groups['project2'])
    new_items.extend(project_groups['other'])
    
    items[:] = new_items


def pytest_runtest_setup(item):
    """Setup Django for the appropriate project before each test."""
    test_path = Path(item.fspath)
    root_path = Path(__file__).parent
    
    if 'project1' in test_path.parts:
        project_path = root_path / 'project1'
        django_manager.setup_project(
            'project1',
            'project1.settings_test',
            project_path
        )
    elif 'project2' in test_path.parts:
        project_path = root_path / 'project2'
        django_manager.setup_project(
            'project2',
            'project2.settings_test',
            project_path
        )


def pytest_sessionfinish(session, exitstatus):
    """Cleanup Django when pytest session finishes."""
    django_manager.teardown_project()
