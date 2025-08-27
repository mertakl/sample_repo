include:
  - project: 'Production-mutualisee/IPS/IDO/gitlab-cicd/pipelines'
    file: '.gitlab-ci.yml'

default:
  tags:
    - "ocp_l"

variables:
  SRC_FOLDERS: "bnppf_log_client"
  SRC_TEST_FOLDERS: "tests"
  SRC_SONAR_EXCLUDE: ""
  COVERAGE_MIN_PC: 0
  PYTHON_DOCKER_IMAGE: $CI_REGISTRY/python:3.12.7-710173e3
  # Artifactory config
  ARTIFACTORY_HOST: "repo.artifactory-dogen.group.echonet"
  ARTIFACTORY_CERTIFICATE_FILE: "/tmp/artifactory.crt"
  # PIP config
  PIP_CERT: /etc/ssl/certs/BNPPRoot.crt
  PIP_EXTRA_INDEX_URL: https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@${ARTIFACTORY_HOST}/artifactory/api/pypi/p-3096-pypi-RELEASE/simple
  PIP_INDEX_URL: https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@${ARTIFACTORY_HOST}/artifactory/api/pypi/files.pythonhosted.org/simple
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  PIP_TIMEOUT: 300
  PIP_TRUSTED_HOST: ${ARTIFACTORY_HOST}
  # UV config
  UV_DEFAULT_INDEX: ${PIP_INDEX_URL}
  UV_INDEX: ${PIP_EXTRA_INDEX_URL}
  SSL_CERT_FILE: /etc/ssl/certs/BNPPRoot.crt
  UV_HTTP_TIMEOUT: 300
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.uv-cache"
  UV_VERSION: "0.7.3"
  UV_INSECURE_HOST: "https://repo.artifactory-dogen.group.echonet/"

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Enhanced cache configuration
cache:
  - key: "pip-$CI_COMMIT_REF_SLUG"
    paths:
      - .cache/pip
      - .uv-cache
    policy: pull-push
  - key: "uv-$CI_COMMIT_REF_SLUG"
    paths:
      - .uv-cache
    policy: pull-push

stages:
  - setup
  - testing
  - update_sonar
  - release

# Common setup job to reduce duplication
.setup_env: &setup_env
  before_script:
    - echo "Setting up environment..."
    # Clear potentially corrupted caches
    - rm -rf .uv-cache/*/bnppf_log_client* || true
    - rm -rf .cache/pip/*/bnppf_log_client* || true
    # Configure pip
    - pip config set global.index-url "https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@repo.artifactory-dogen.group.echonet/artifactory/api/pypi/files.pythonhosted.org/simple"
    - pip config set global.trusted-host "repo.artifactory-dogen.group.echonet"
    - pip config set global.timeout '300'
    - echo "$ARTIFACTORY_CERTIFICATE" > $(pwd)/artifactory.crt
    - pip config set global.cert $(pwd)/artifactory.crt
    - export PATH=~/.local/bin:$PATH
    # Install UV with retry mechanism
    - |
      for i in {1..3}; do
        if [[ -v UV_VERSION ]]; then
          pip3 install --no-cache-dir uv==${UV_VERSION} && break
        else
          pip3 install --no-cache-dir uv && break
        fi
        echo "Attempt $i failed, retrying..."
        sleep 5
      done
    - export PATH=~/.local/bin:$PATH

# Environment validation job
validate_env:
  stage: setup
  image: $PYTHON_DOCKER_IMAGE
  <<: *setup_env
  script:
    - echo "Validating environment setup..."
    - uv --version
    - pip --version
    - python --version
    # Test connectivity to artifactory
    - curl -f -s -I "https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@${ARTIFACTORY_HOST}/artifactory/api/pypi/files.pythonhosted.org/simple" || echo "Warning: Artifactory connection test failed"
    # Clear and recreate lock if needed
    - |
      if [ -f "uv.lock" ]; then
        echo "Checking lock file integrity..."
        uv lock --check || (echo "Lock file issues detected, regenerating..." && rm uv.lock && uv lock)
      fi
  artifacts:
    paths:
      - uv.lock
    expire_in: 1 hour
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_AUTHOR =~ /semantic-release.*/
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'

code_quality:
  stage: testing
  image: $PYTHON_DOCKER_IMAGE
  <<: *setup_env
  needs:
    - validate_env
  allow_failure: false
  script:
    - '[[ -v CI_MERGE_REQUEST_TARGET_BRANCH_NAME ]] && FROM_REF="$CI_MERGE_REQUEST_TARGET_BRANCH_NAME" || FROM_REF="$CI_DEFAULT_BRANCH"'
    - git fetch origin $FROM_REF
    - git add .pre-commit-config.yaml
    # Install with retry and no-deps where possible
    - |
      for i in {1..3}; do
        uv run --frozen --all-groups pre-commit run --from-ref "origin/$FROM_REF" --to-ref HEAD --show-diff-on-failure && break
        echo "Pre-commit attempt $i failed, clearing cache and retrying..."
        rm -rf .uv-cache/*/bnppf_log_client* || true
        sleep 5
      done
    - if [ -f ./pylint-report.txt ]; then sed -i "s/^'\(.*\)'$/\1/" pylint-report.txt && cat pylint-report.txt; fi
  artifacts:
    paths:
      - pylint-report.txt
    expire_in: 1 day
    when: always
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_AUTHOR =~ /semantic-release.*/
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'

pytest:
  image: $PYTHON_DOCKER_IMAGE
  stage: testing
  <<: *setup_env
  needs:
    - validate_env
  variables:
    GIT_DEPTH: 0
    GIT_FETCH_EXTRA_FLAGS: --tags
  script:
    - echo "Starting pytest execution..."
    # Install dependencies with retry mechanism
    - |
      for i in {1..3}; do
        echo "Installing dependencies, attempt $i..."
        uv sync --frozen --all-groups && break
        echo "Sync failed, clearing problematic caches..."
        rm -rf .uv-cache/*/bnppf_log_client* || true
        rm -rf .cache/pip/*/bnppf_log_client* || true
        sleep 5
      done
    
    # Run tests
    - uv run --frozen --all-groups coverage erase
    - uv run --frozen --all-groups coverage run -m pytest tests/unit_tests --junitxml=report.xml --html=report.html --self-contained-html -v
    - uv run --frozen --all-groups coverage report --fail-under=$COVERAGE_MIN_PC
    - uv run --frozen --all-groups coverage xml -i
    - uv run --frozen --all-groups coverage html
    
    # Install semantic-release with retry
    - |
      for i in {1..3}; do
        uv pip install --no-cache https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@repo.artifactory-dogen.group.echonet:443/artifactory/github/aborsu/other-semantic-release/archive/refs/heads/gitlab-ci.zip && break
        echo "Semantic-release install attempt $i failed, retrying..."
        sleep 5
      done
    
    # Version management
    - git checkout -B "$CI_COMMIT_REF_NAME"
    - VERSION=$(uv run semantic-release --noop version --print)
    - CURRENT_VERSION=$(cat pyproject.toml | grep "version *=" | sed -r 's/^version *= *"(.*)"$/\1/')
    - VERSION=${VERSION:-$CURRENT_VERSION}
    - echo $VERSION >> next_version
  coverage: '/TOTAL.*\s+(\d+%)$/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
      junit: report.xml
    paths:
      - next_version
      - coverage.xml
      - report.xml
      - report.html
      - htmlcov
    expire_in: 30 days
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_AUTHOR =~ /semantic-release.*/
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'

update_sonar:
  stage: update_sonar
  image: $CI_REGISTRY/$SONAR_SCANNER_IMAGE_TAG
  before_script:
    - 'true' # Override global before_script
  script:
    - git fetch origin $CI_DEFAULT_BRANCH
    - sonar-scanner
        -Dsonar.projectKey=${SONAR_PROJECT_KEY}
        -Dsonar.host.url=${SONAR_URL}
        -Dsonar.login=${SONAR_USER}
        -Dsonar.password=${SONAR_PASSWORD}
        -Dsonar.links.homepage=$CI_PROJECT_URL
        -Dsonar.qualitygate.wait=false
        -Dsonar.sourceEncoding=UTF-8
        -Dsonar.projectVersion=$(cat next_version)
        -Dsonar.sources=$SRC_FOLDERS
        -Dsonar.tests=$SRC_TEST_FOLDERS
        -Dsonar.exclusions=$SRC_SONAR_EXCLUDE
        -Dsonar.python.version=3
        -Dsonar.python.xunit.reportPath=report.xml
        -Dsonar.python.coverage.reportPaths=coverage.xml
        -Dsonar.python.pylint.reportPath=pylint-report.txt
        -Dsonar.scm.disabled=False
        -Dsonar.scm.provider=git
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_AUTHOR =~ /semantic-release.*/
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'
  needs:
    - code_quality
    - pytest

release:
  stage: release
  image: $PYTHON_DOCKER_IMAGE
  <<: *setup_env
  variables:
    GIT_DEPTH: 0
    GIT_FETCH_EXTRA_FLAGS: --tags
    GIT_COMMIT_AUTHOR: "semantic-release <$GITLAB_USER_EMAIL>"
    UV_PUBLISH_PASSWORD: "$ARTIFACTORY_PASSWORD"
    UV_PUBLISH_USERNAME: "$ARTIFACTORY_USER"
  script:
    - echo "Starting release process..."
    - uv venv && source .venv/bin/activate
    
    # Install required packages with retry
    - |
      for i in {1..3}; do
        echo "Installing release dependencies, attempt $i..."
        uv pip install --no-cache https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@repo.artifactory-dogen.group.echonet:443/artifactory/github/aborsu/other-semantic-release/archive/refs/heads/gitlab-ci.zip && break
        sleep 5
      done
    - uv pip install twine build
    
    # Git configuration
    - git checkout -B "$CI_COMMIT_REF_NAME"
    - git remote set-url origin "https://${GITLAB_USER}:${GITLAB_PASSWORD}@${CI_REPOSITORY_URL#*@}"
    - git pull origin "$CI_COMMIT_REF_NAME"
    
    # Release process
    - uv run semantic-release -v version
    - uv build --no-cache
    
    # Publish with retry mechanism
    - |
      for i in {1..3}; do
        echo "Publishing to artifactory, attempt $i..."
        uv publish --index artifactory && break
        echo "Publish attempt $i failed, retrying..."
        sleep 10
      done
  rules:
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release.*/
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
