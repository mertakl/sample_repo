error: Local file and index file do not match for bnppf_log_client-0.5.6.tar.gz. Local: sha256=a24eebd68235f7e41b9cb261e00c0eaf025a814ae0443c1928404657fe371b13, Remote: sha256=0c193ac4b21e0e4e593aa3da0b9564d57c94939106b288bb7bfa81c4abbe7c40



include:
  # Include Global shared job definitions and variables.
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
  UV_CACHE_DIR: .uv-cache
  UV_VERSION: "0.7.3"
  UV_INSECURE_HOST: "https://repo.artifactory-dogen.group.echonet/"

workflow:
  rules:
    # run on merge requests
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'
    # run when pushing to the default branch (master/main)
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

cache:
  paths:
    - .cache/pip

stages:
  - testing
  - update_sonar
  - release

before_script:
  - pip config set global.index-url "https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@repo.artifactory-dogen.group.echonet/artifactory/api/pypi/files.pythonhosted.org/simple"
  - pip config set global.trusted-host "repo.artifactory-dogen.group.echonet"
  - pip config set global.timeout '300'
  - echo "$ARTIFACTORY_CERTIFICATE" > $(pwd)/artifactory.crt
  - pip config set global.cert $(pwd)/artifactory.crt
  - export PATH=~/.local/bin:$PATH
  - if [[ -v UV_VERSION ]]; then pip3 install uv==${UV_VERSION}; else pip3 install uv; fi
  - export PATH=~/.local/bin:$PATH

code_quality:
  stage: testing
  image: $PYTHON_DOCKER_IMAGE
  allow_failure: no
  script:
    - '[[ -v CI_MERGE_REQUEST_TARGET_BRANCH_NAME ]] && FROM_REF="$CI_MERGE_REQUEST_TARGET_BRANCH_NAME" || FROM_REF="$CI_DEFAULT_BRANCH"'
    - git fetch origin $FROM_REF
    - git add .pre-commit-config.yaml
    - uv run --frozen --all-groups pre-commit run --from-ref "origin/$FROM_REF" --to-ref HEAD --show-diff-on-failure
    - if [ -f ./pylint-report.txt ]; then sed -i "s/^'\(.*\)'$/\1/" pylint-report.txt && cat pylint-report.txt; fi
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_AUTHOR =~ /semantic-release.*/
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'

pytest:
  ## We are currently running pytest and pylint in a single stage as they require the environment to be built
  image: $PYTHON_DOCKER_IMAGE
  stage: testing
  variables:
    GIT_DEPTH: 0
    GIT_FETCH_EXTRA_FLAGS: --tags
  script:
    - uv run --frozen --all-groups coverage erase
    - uv run --frozen --all-groups coverage run -m pytest tests/unit_tests --junitxml=report.xml --html=report.html --self-contained-html
    - uv run --frozen --all-groups coverage report --fail-under=$COVERAGE_MIN_PC
    - uv run --frozen --all-groups coverage xml -i
    - uv run --frozen --all-groups coverage html
    - uv pip install https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@repo.artifactory-dogen.group.echonet:443/artifactory/github/aborsu/other-semantic-release/archive/refs/heads/gitlab-ci.zip
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
  before_script: # to override the global before_script
    - 'true'
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
  variables:
    GIT_DEPTH: 0
    GIT_FETCH_EXTRA_FLAGS: --tags
    GIT_COMMIT_AUTHOR: "semantic-release <$GITLAB_USER_EMAIL>"
    UV_PUBLISH_PASSWORD: "$ARTIFACTORY_PASSWORD"
    UV_PUBLISH_USERNAME: "$ARTIFACTORY_USER"
  script:
    - uv venv && source .venv/bin/activate
    - uv pip install https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@repo.artifactory-dogen.group.echonet:443/artifactory/github/aborsu/other-semantic-release/archive/refs/heads/gitlab-ci.zip
    - uv pip install twine build
    - git checkout -B "$CI_COMMIT_REF_NAME"
    - git remote set-url origin "https://${GITLAB_USER}:${GITLAB_PASSWORD}@${CI_REPOSITORY_URL#*@}"
    - git pull origin "$CI_COMMIT_REF_NAME"
    - uv run semantic-release -v version
    - uv build
    - uv publish --index artifactory
  rules:
    # Don't run on automatic commits
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release.*/
      when: never
    # Only run on main/master branch
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
