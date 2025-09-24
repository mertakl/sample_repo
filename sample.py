# -----------------------
# New, Optimized Stages
# -----------------------
stages:
  - build_and_test
  - analysis
  - release

# ----------------------------------------
# TEMPLATES for Reusability (DRY Principle)
# ----------------------------------------
.base_job_template:
  retry: 2
  rules:
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release/
      when: never
    - when: on_success

.python_job_template:
  extends: .base_job_template
  image: $CI_REGISTRY/python:1.0.1
  cache:
    key:
      files:
        - requirements/requirements_domino_ci.txt
        - requirements/code_quality.txt
    paths:
      - .cache/pip
  before_script:
    - export PIP_CACHE_DIR="$CI_PROJECT_DIR/.cache/pip"

# ----------------------------------
# Stage 1: Build & Test (Parallel)
# ----------------------------------
build_image:
  stage: build_and_test
  extends: .base_job_template
  image: $CI_REGISTRY/$CLOUDOTOOLS_IMAGE_TAG
  tags:
    - "ocp_xl"
  variables:
    DOCKER_IMAGE_NAME: "aisc-ap04"
    PROJECT_DOCKER_SPACE: "np-3096-docker-local"
    PROJECT_DOCKER_REGISTRY: "$PROJECT_DOCKER_SPACE.artifactory-dogen.group.echonet"
    PROJECT_DOCKER_SPACE_3096: "p-3096-docker-local"
    PROJECT_DOCKER_REGISTRY_3096: "$PROJECT_DOCKER_SPACE_3096.artifactory-dogen.group.echonet"
    IMAGE_TAG: "$CI_COMMIT_SHA"
  rules: # Override rules to handle tags
    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'
    - if: $CI_COMMIT_TAG
      variables:
        IMAGE_TAG: "$CI_COMMIT_TAG"
  script:
    # Use --cache-from to speed up builds
    - IMAGE_URL="$PROJECT_DOCKER_REGISTRY/$DOCKER_IMAGE_NAME:$IMAGE_TAG"
    - docker login $PROJECT_DOCKER_REGISTRY -u $ARTIFACTORY_USER -p $ARTIFACTORY_PASSWORD
    - docker login $PROJECT_DOCKER_REGISTRY_3096 -u $ARTIFACTORY_3096_USER -p $ARTIFACTORY_3096_PASSWORD
    - echo "Attempting to use cache from $IMAGE_URL"
    - docker pull $IMAGE_URL || true # Allow to fail if the image doesn't exist
    - echo "Building image with tag: $IMAGE_TAG"
    - docker build . \
        --cache-from $IMAGE_URL \
        --network=host \
        --label=bnpp.container.governance.image.auid="AP87605" \
        --label .multiple --label here \
        -t $IMAGE_URL \
        --progress=plain \
        --build-arg ARTIFACTORY_USER=$ARTIFACTORY_3096_USER
    - docker push $IMAGE_URL

pytest:
  stage: build_and_test
  extends: .python_job_template
  needs: [] # Runs in parallel with others in this stage
  before_script:
    - !reference [.python_job_template, before_script] # Inherit base before_script
    - python -m pip install -r requirements/requirements_domino_ci.txt
  script:
    - python -m ci.scripts.call_tests_domino ... # Arguments omitted for brevity
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

code_quality:
  stage: build_and_test
  extends: .python_job_template
  allow_failure: true
  needs: []
  before_script:
    - !reference [.python_job_template, before_script]
    - python -m pip install -r requirements/code_quality.txt
  script:
    - git fetch origin
    - pre-commit run --all-files

get_next_version:
  stage: build_and_test
  extends: .python_job_template
  needs: []
  before_script:
    - !reference [.python_job_template, before_script]
    - python -m pip install python-semantic-release==10.3.0
  script:
    - '[[ -v CI_MERGE_REQUEST_TARGET_BRANCH_NAME ]] && FROM_REF="$CI_MERGE_REQUEST_SOURCE_BRANCH_NAME" || FROM_REF="$CI_DEFAULT_BRANCH"'
    - git fetch origin $FROM_REF
    - git checkout $FROM_REF
    - git pull
    - VERSION=$(semantic-release --noop version --print)
    - CURRENT_VERSION=$(cat pyproject.toml | grep "version *=" | sed -r 's/^version *= *"(.*)"/\1/')
    - VERSION=${VERSION:-$CURRENT_VERSION}
    - echo $VERSION > next_version
  artifacts:
    paths:
      - next_version
    expire_in: 30 days

# ---------------------------------
# Stage 2: Analysis (Parallel)
# ---------------------------------
retriever-eval:
  stage: analysis
  extends: .python_job_template
  allow_failure: true
  needs: ["pytest", "get_next_version"]
  before_script:
    - !reference [.python_job_template, before_script]
    - python -m pip install -r requirements/requirements_domino_ci.txt
  script:
    - python -m ci.scripts.call_retriever_eval.domino ... # Arguments omitted for brevity
  after_script:
    - echo "See experiment results at https://dmn-ap26762-prod-c1bf2d58.datalab.cloud.echonet/experiments/fortis/aisc-ap04-ci"

update_sonar:
  stage: analysis
  extends: .base_job_template
  allow_failure: true
  image: $CI_REGISTRY/$SONAR_SCANNER_IMAGE_TAG
  tags:
    - "ocp_l"
  needs: ["pytest", "get_next_version"]
  script:
    - sonar-scanner
        -Dsonar.projectKey=${SONAR_PROJECT_KEY}
        -Dsonar.host.url=${SONAR_URL}
        -Dsonar.login=${SONAR_USER}
        -Dsonar.password=${SONAR_PASSWORD}
        -Dsonar.projectVersion=$(cat next_version)
        -Dsonar.python.xunit.reportPaths=report.xml
        -Dsonar.python.coverage.reportPaths=coverage.xml
        -Dsonar.python.pylint.reportPaths=pylint-report.txt
        # Other parameters omitted for brevity

# -----------------------
# Stage 3: Release
# -----------------------
release:
  stage: release
  extends: .python_job_template
  variables:
    EMAIL: "AAIPLATFORMSSUPPORT@bnpparibasfortis.com"
    GIT_AUTHOR_NAME: "semantic release"
    GIT_COMMITTER_NAME: "semantic release"
    TWINE_PASSWORD: "$ARTIFACTORY_3096_PASSWORD"
    TWINE_USERNAME: "$ARTIFACTORY_3096_USER"
    TWINE_REPOSITORY_URL: "$ARTIFACTORY_URL/api/pypi/p-3096-pypi-RELEASE"
  rules: # Custom rules for this job
    - if: $CI_COMMIT_AUTHOR =~ /semantic-release.*/
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  before_script:
    - !reference [.python_job_template, before_script]
    - pip
