# conftest.py (at root)
import os
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "project1: mark test as part of project1")
    config.addinivalue_line("markers", "project2: mark test as part of project2")

def pytest_collection_modifying(session, config, items):
    # Group tests by project
    project1_tests = [item for item in items if 'project1' in str(item.fspath)]
    project2_tests = [item for item in items if 'project2' in str(item.fspath)]
    
    # Run them separately
    if project1_tests and project2_tests:
        pytest.exit("Cannot run both projects together. Run separately.")

@pytest.fixture(scope='session', autouse=True)
def django_settings(request):
    test_path = str(request.fspath)
    
    if 'project1' in test_path:
        os.environ['DJANGO_SETTINGS_MODULE'] = 'project1.settings'
    elif 'project2' in test_path:
        os.environ['DJANGO_SETTINGS_MODULE'] = 'project2.settings'
