import pytest

@pytest.fixture(autouse=True, scope="session")
def set_django_settings():
    import os
    os.environ["DJANGO_SETTINGS_MODULE"] = "project_a.settings"
