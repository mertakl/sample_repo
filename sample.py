stages:
  - test_and_quality    # Run tests first - no dependency on build
  - build              # Build only when needed
  - evaluation         # Depends on tests, not build
  - sonar_and_release  # Parallelized final stages

# -----------------------
# Build Stage
# -----------------------
build_image:
  stage: build
  allow_failure: true
  variables:
    DOCKER_IMAGE_NAME: "aisc-ap04"
    PROJECT_DOCKER_SPACE: "np-3096-docker-local"
    PROJECT_DOCKER_REGISTRY: "$PROJECT_DOCKER_SPACE.artifactory-dogen.group.echonet"
    PROJECT_DOCKER_SPACE_3096: "p-3096-docker-local"
    PROJECT_DOCKER_REGISTRY_3096: "$PROJECT_DOCKER_SPACE_3096.artifactory-dogen.group.echonet"
    IMAGE_TAG: "$CI_COMMIT_SHA"
    TEMPORARY_BRANCH_BUILD: "true"
    DOCKER_BUILDKIT: 1  # Enable BuildKit for faster builds
    BUILDKIT_PROGRESS: plain
  image: $CI_REGISTRY/$CLOUDOTOOLS_IMAGE_TAG
  tags:
    - "ocp_xl"
  rules:
    # Only build on main branch, tags, or when specifically requested
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_TAG
      variables:
        IMAGE_TAG: "$CI_COMMIT_TAG"
        TEMPORARY_BRANCH_BUILD: "false"
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event' && $BUILD_IMAGE == "true"
      variables:
        IMAGE_TAG: "$CI_COMMIT_SHA"
        TEMPORARY_BRANCH_BUILD: "true"
    - when: manual  # Allow manual trigger from MRs
      allow_failure: true
  before_script:
    # Combine docker logins to reduce redundancy
    - docker login $PROJECT_DOCKER_REGISTRY -u $ARTIFACTORY_USER -p $ARTIFACTORY_PASSWORD
    - docker login $PROJECT_DOCKER_REGISTRY_3096 -u $ARTIFACTORY_3096_USER -p $ARTIFACTORY_3096_PASSWORD
  script:
    - echo "Using IMAGE_TAG=$IMAGE_TAG, temporary branch build = $TEMPORARY_BRANCH_BUILD"
    # Use BuildKit with cache mounts and multi-stage optimization
    - docker build . \
        --network=host \
        --label=bnpp.container.governance.image.auid="AP87605" \
        --label .multiple --label here \
        -t $PROJECT_DOCKER_REGISTRY/$DOCKER_IMAGE_NAME:$IMAGE_TAG \
        --cache-from $PROJECT_DOCKER_REGISTRY/$DOCKER_IMAGE_NAME:latest \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        --build-arg ARTIFACTORY_USER=$ARTIFACTORY_3096_USER
    - docker push $PROJECT_DOCKER_REGISTRY/$DOCKER_IMAGE_NAME:$IMAGE_TAG
  cache:
    key: docker-$CI_COMMIT_REF_SLUG
    paths:
      - .docker/
  retry:
    max: 2
    when: runner_system_failure
  needs:
    # Only build after tests pass (fast feedback)
    - job: pytest
      artifacts: false
    - job: code_quality
      artifacts: false

# -----------------------
# Parallel Test & Quality Stage
# -----------------------
pytest:
  stage: test_and_quality  # Now runs in parallel with other jobs
  extends: .config_artifactory_template
  image: $CI_REGISTRY/python:1.0.1
  allow_failure: false
  variables:
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  cache:
    key: pip-$CI_COMMIT_REF_SLUG
    paths:
      - .cache/pip/
      - .pytest_cache/
  script:
    # Template's before_script runs automatically, then our setup
    - python -m pip install --upgrade pip
    - python -m pip install -r requirements/requirements_domino_ci.txt
    - python -m ci.scripts.call_tests_domino
        --domino_url ${DOMINO_URL}
        --domino_api_key ${DOMINO_API_KEY}
        --domino_project_name ${DOMINO_PROJECT_NAME}
        --domino_project_owner ${DOMINO_PROJECT_OWNER}
        --git_commit_sha ${CI_COMMIT_SHA}
        --domino_hardware_tier ${DOMINO_HARDWARE_TIER_TEST}
        --domino_env_id ${DOMINO_ENV_ID}
        --domino_revision_env ${DOMINO_REVISION_ENV}
        --src_folders ${SRC_FOLDERS}
        --coverage_min_pc ${COVERAGE_MIN_PC}
  after_script:
    - echo "See the test report at https://gitlab-dogen.group.echonet/dm/fortis/tribe_artificial_intelligence/aisc/aisc-ap04/-/pipelines/${CI_PIPELINE_ID}/test_report"
  coverage: '/TOTAL.*\s+(\d+%)/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
      junit: report.xml
    paths:
      - coverage.xml
      - report.xml
      - report.html
      - pylint-report.txt
      - domino_metadata.json
      - domino_support_bundle.zip
    expire_in: 30 days
  rules:
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release/
      when: never
    - when: on_success
  retry:
    max: 2
    when: script_failure

code_quality:
  stage: test_and_quality  # Now runs in parallel with pytest
  extends: .config_artifactory_template
  allow_failure: true
  variables:
    PRE_COMMIT_HOME: "$CI_PROJECT_DIR/.cache/pre-commit"
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  cache:
    key: code-quality-$CI_COMMIT_REF_SLUG
    paths:
      - .cache/pip/
      - .cache/pre-commit/
  script:
    # Template's before_script runs automatically, then our setup
    - git fetch origin --depth=50  # Limit fetch depth for speed
    - python -m pip install --upgrade pip
    - python -m pip install -r requirements/code_quality.txt
    - pre-commit run --all-files
  retry:
    max: 2
    when: script_failure

get_next_version:
  stage: test_and_quality  # Now runs in parallel
  extends: .config_artifactory_template
  allow_failure: false
  variables:
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  cache:
    key: version-$CI_COMMIT_REF_SLUG
    paths:
      - .cache/pip/
  script:
    # Template's before_script runs automatically, then our setup
    - python -m pip install --upgrade pip
    - python -m pip install python-semantic-release==10.3.0
    - '[[ -v CI_MERGE_REQUEST_TARGET_BRANCH_NAME ]] && FROM_REF="$CI_MERGE_REQUEST_SOURCE_BRANCH_NAME" || FROM_REF="$CI_DEFAULT_BRANCH"'
    - git fetch origin $FROM_REF --depth=50
    - git checkout $FROM_REF
    - echo "The current branch is $FROM_REF"
    - git pull
    - VERSION=$(semantic-release --noop version --print)
    - CURRENT_VERSION=$(grep -E "version *= *" pyproject.toml | sed -r 's/^version *= *"(.*)"/\1/')
    - VERSION=${VERSION:-$CURRENT_VERSION}
    - echo $VERSION | tee next_version
  artifacts:
    paths:
      - next_version
    expire_in: 30 days
  rules:
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release/
      when: never
    - when: on_success
  retry:
    max: 2
    when: script_failure

# -----------------------
# Evaluation Stage (depends on tests)
# -----------------------
retriever-eval:
  stage: evaluation
  extends: .config_artifactory_template
  image: $CI_REGISTRY/python:1.0.1
  allow_failure: true
  variables:
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  cache:
    key: eval-$CI_COMMIT_REF_SLUG
    paths:
      - .cache/pip/
  script:
    # Template's before_script runs automatically, then our setup
    - python -m pip install --upgrade pip
    - python -m pip install -r requirements/requirements_domino_ci.txt
    - python -m ci.scripts.call_retriever_eval.domino
        --domino_url ${DOMINO_URL}
        --domino_api_key ${DOMINO_API_KEY}
        --domino_project_name ${DOMINO_PROJECT_NAME}
        --domino_project_owner ${DOMINO_PROJECT_OWNER}
        --git_commit_sha ${CI_COMMIT_SHA}
        --domino_hardware_tier ${DOMINO_HARDWARE_TIER_TEST}
        --domino_env_id ${DOMINO_ENV_ID}
        --domino_revision_env ${DOMINO_REVISION_ENV}
        --experiment_name ${RETRIEVER_EVAL_EXPERIMENT}
  after_script:
    - echo "See the experiment results at https://dmn-ap26762-prod-c1bf2d58.datalab.cloud.echonet/experiments/fortis/aisc-ap04-ci"
  rules:
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release/
      when: never
    - when: on_success
  needs:
    - job: pytest
      artifacts: false  # Don't need artifacts, just job completion
    - job: get_next_version
      artifacts: true   # Need the version file

# -----------------------
# Parallel Final Stage
# -----------------------
update_sonar:
  stage: sonar_and_release  # Now runs in parallel with release
  allow_failure: true
  image: $CI_REGISTRY/$SONAR_SCANNER_IMAGE_TAG
  script:
    - |
      sonar-scanner \
        -Dsonar.projectKey=${SONAR_PROJECT_KEY} \
        -Dsonar.host.url=${SONAR_URL} \
        -Dsonar.login=${SONAR_USER} \
        -Dsonar.password=${SONAR_PASSWORD} \
        -Dsonar.links.homepage=$CI_PROJECT_URL \
        -Dsonar.projectVersion=$(cat next_version) \
        -Dsonar.sources=$SRC_FOLDERS \
        -Dsonar.tests=$SRC_TEST_FOLDERS \
        -Dsonar.python.version=3 \
        -Dsonar.python.xunit.reportPaths=report.xml \
        -Dsonar.python.coverage.reportPaths=coverage.xml \
        -Dsonar.python.pylint.reportPaths=pylint-report.txt \
        -Dsonar.scm.disabled=False \
        -Dsonar.scm.provider=git
  rules:
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release/
      when: never
    - when: on_success
  retry:
    max: 2
    when: script_failure
  needs:
    - job: pytest
      artifacts: true   # Need test artifacts
    - job: get_next_version
      artifacts: true   # Need version file
  tags:
    - "ocp_l"

release:
  stage: sonar_and_release  # Now runs in parallel with sonar
  extends: .config_artifactory_template
  image: $CI_REGISTRY/python:1.0.1
  variables:
    EMAIL: "AAIPLATFORMSSUPPORT@bnpparibasfortis.com"
    GIT_AUTHOR_NAME: "semantic release"
    GIT_COMMITTER_NAME: "semantic release"
    TWINE_PASSWORD: "$ARTIFACTORY_3096_PASSWORD"
    TWINE_USERNAME: "$ARTIFACTORY_3096_USER"
    TWINE_REPOSITORY_URL: "$ARTIFACTORY_URL/api/pypi/p-3096-pypi-RELEASE"
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  cache:
    key: release-$CI_COMMIT_REF_SLUG
    paths:
      - .cache/pip/
  script:
    # Template's before_script runs automatically, then our setup
    - python -m pip install --upgrade pip
    - pip install python-semantic-release==10.3.0 twine build
    - git fetch origin $CI_COMMIT_REF_NAME --depth=50
    - git checkout $CI_COMMIT_REF_NAME
    - echo "The current branch is $CI_COMMIT_REF_NAME"
    - git pull
    - git checkout -B "$CI_COMMIT_REF_NAME"
    - git remote set-url origin "https://:${GITLAB_PASSWORD}@${CI_REPOSITORY_URL#*@}"
    - semantic-release version
    - |
      if [ -d "dist" ] && [ "$(ls -A dist)" ]; then
        python -m twine upload dist/*
      else
        echo "No distribution files found or dist directory is empty"
      fi
  rules:
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release.*/
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  needs:
    - job: get_next_version
      artifacts: false  # Don't need artifacts for release

# -----------------------
# Global Configuration
# -----------------------
default:
  interruptible: true  # Allow jobs to be interrupted by newer pipelines
  
workflow:
  rules:
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never  # Don't run on branch if MR exists
    - when: always

# -----------------------
# Optional: Deployment Job (Example)
# -----------------------
# deploy_to_staging:
#   stage: deploy
#   script:
#     - echo "Deploying image $PROJECT_DOCKER_REGISTRY/$DOCKER_IMAGE_NAME:$CI_COMMIT_SHA"
#     # Your deployment logic here
#   needs:
#     - job: build_image
#       artifacts: false
#   rules:
#     - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
#   when: manual
