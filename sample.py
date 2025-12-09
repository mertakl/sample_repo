import pytest

@pytest.fixture(autouse=True, scope="session")
def set_django_settings():
    import os
    os.environ["DJANGO_SETTINGS_MODULE"] = "project_a.settings"


[pytest]
DJANGO_SETTINGS_MODULE =
testpaths =
    project_a/tests
    project_b/tests

markers =
    project_a: Tests for Project A (uses project A settings)
    project_b: Tests for Project B (uses project B settings)


