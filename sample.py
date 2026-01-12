include:
  - project: "Production-mutualisee/IPS/IDO/gitlab-cicd/pipelines"
    file: ".gitlab-ci.yml"

default:
  tags:
    - "ocp_xl"

variables:
  DOCKER_IMAGE_NAME: "aidi/aidi-ta02"

# Consolidated workflow rules - run on MRs and specific branch conditions
workflow:
  rules:
    - if: $CI_COMMIT_TAG
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^\(\d+\.\d+\.\d+\)/
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch\//
    - if: $CI_COMMIT_BRANCH
    - if: $CI_MERGE_REQUEST_TARGET_BRANCH_NAME

before_script:
  - if [[ -v UV_VERSION ]]; then pip3 install uv==${UV_VERSION}; else pip3 install uv; fi
  - export PATH=/.local/bin:$PATH

.default_rules: &default_rules
  rules:
    # Skip on master merge commits (already tested in MR)
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch\//
      when: never
    # Run on feature branches
    - if: $CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH
    # Run on tags
    - if: $CI_COMMIT_TAG

.master_only_rules: &master_only_rules
  rules:
    # Only run on master for version tags or explicit deployments
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^\(\d+\.\d+\.\d+\)/
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch\//
      when: never

stages:
  - build_image
  - testing
  - update_sonar
  - marvin_release
  - security_scans

# ============================================================================
# BUILD STAGE
# ============================================================================
build:
  stage: build_image
  image: $CI_REGISTRY/$CLOUDTOOLS_IMAGE_TAG
  before_script:
    - "# Override global before_script"
  timeout: 3h
  script:
    - docker login $PROJECT_DOCKER_REGISTRY -u $ARTIFACTORY_USER -p $ARTIFACTORY_PASSWORD
    - docker build
      -t $DOCKER_IMAGE_NAME:$CI_COMMIT_SHA
      --network=host
      --progress=plain
      --build-arg ARTIFACTORY_USER=${ARTIFACTORY_USER}
      --build-arg ARTIFACTORY_PASSWORD=${ARTIFACTORY_PASSWORD}
      --cache-from $DOCKER_IMAGE_NAME:$CI_COMMIT_SHA
      .
  <<: *default_rules
  
  after_script:
    - docker images
  needs: []
  rules:
    - !reference [.default_rules, rules]

# ============================================================================
# TESTING STAGE
# ============================================================================
code_quality:
  stage: testing
  image: $CI_REGISTRY/python:3.12
  script:
    - '![[ -v CI_MERGE_REQUEST_TARGET_BRANCH_NAME ]] && FROM_REF="$CI_MERGE_REQUEST_TARGET_BRANCH_NAME" || FROM_REF="$CI_DEFAULT_BRANCH"'
    - git fetch origin $FROM_REF
    - uv run --dev --no-cache pre-commit run --from-ref "origin/$FROM_REF" --to-ref HEAD --show-diff-on-failure
    - uv run --dev --no-cache ruff check --output-format=gitlab > gl-code-quality-report.json
  <<: *default_rules
  artifacts:
    reports:
      codequality: gl-code-quality-report.json

pytest:
  stage: testing
  image: $CI_REGISTRY/python:3.12
  script:
    - uv run --group test --no-cache bash -c "
      coverage erase &&
      export DJANGO_SETTINGS_MODULE=django_project.settings.local &&
      python manage.py migrate &&
      coverage run -m pytest tests/functional --junitxml=report_test.xml &&
      coverage report --fail-under=\"${COVERAGE_MIN_PC}\" &&
      coverage xml -i &&
      coverage html"
  coverage: '/TOTAL.*\s+(\d+)%/'
  <<: *default_rules
  artifacts:
    reports:
      codequality: gl-code-quality-report.json
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
      junit: report_test.xml
    paths:
      - coverage.xml
      - report.xml
      - report.html
      - htmlcov/
      - pylint-report.txt
    expire_in: 30 days

# ============================================================================
# SONAR ANALYSIS
# ============================================================================
update_sonar:
  stage: update_sonar
  image: $CI_REGISTRY/$SONAR_SCANNER_IMAGE_TAG
  before_script:
    - "# Override global before_script"
  allow_failure: false
  script:
    - sonar-scanner
      -Dsonar.projectKey=${SONAR_PROJECT_KEY}
      # ... rest of sonar config
  needs:
    - job: code_quality
      artifacts: true
    - job: pytest
      artifacts: true
  rules:
    # Run on feature branches and master (for tracking)
    - if: $CI_COMMIT_BRANCH

# ============================================================================
# RELEASE TO MARVIN (Master Only)
# ============================================================================
marvin_release:
  stage: marvin_release
  image: $CI_REGISTRY/$CLOUDTOOLS_IMAGE_TAG
  before_script:
    - "# Override global before_script"
  script:
    - set -xv &&
      wget -S --no-check-certificate --header='Content-Type: application/json' --post-data "{
        \"PROJECT\":\"$CI_PROJECT_PATH\",
        \"APPLICATION_CODE\":\"$APP_NAME\",
        \"PUBLISH_GITLAB\":\"$PUBLISH_GITLAB\",
        \"PUBLISH_DOCKER\":\"$PUBLISH_DOCKER\",
        \"APP_NAME\":\"$APP_NAME\",
        \"APCODE\":\"$APCODE\",
        \"DESCRIPTION\":\"$DESCRIPTION\",
        \"MARVIN_AP_CODE\":\"$MARVIN_AP_CODE\",
        \"MARVIN_DEV_ENV\":\"$MARVIN_DEV_ENV\",
        \"ENABLE_RELEASE_MARVIN\":\"$ENABLE_RELEASE_MARVIN\",
        \"ARTIFACTORY_3098_ENABLED\":\"$ARTIFACTORY_3098_ENABLED\",
        \"CREDENTIAL_NAME\":\"$CREDENTIAL_NAME\"
      }" $JENKINS_URL/generic-webhook-trigger/invoke?token=$JENKINS_MARVIN_RELEASE_TOKEN
  <<: *master_only_rules
  needs:
    - job: update_sonar

# ============================================================================
# SECURITY SCANS (Master Only)
# ============================================================================
security_scans:
  stage: security_scans
  image: $CI_REGISTRY/$CLOUDTOOLS_IMAGE_TAG
  before_script:
    - "# Override global before_script"
  script:
    - wget --no-check-certificate -S --header='Content-Type: application/json' --post-data "{
        \"ENABLE_NEXUS_IQ\":\"true\",
        \"ENABLE_FORTIFY\":\"true\",
        \"PROJECT_PATH_MAP\":\"dm/fortis/tribe_artificial_intelligence/aidi/aidi-ta02:AIDI\",
        \"BRANCH\":\"$CI_COMMIT_BRANCH\",
        \"DECLARE_PROJECT_IN_FORTIFY_AND_NEXUSIQ\":\"false\",
        \"CREDENTIAL_NAME\":\"$CREDENTIAL_NAME\"
      }" $JENKINS_URL/generic-webhook-trigger/invoke?token=$JENKINS_TOKEN
  <<: *master_only_rules
  needs:
    - job: update_sonar
