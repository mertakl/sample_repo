# ==========================================================================
# Reusable CI components using YAML anchors
# ==========================================================================
.job_templates:
  # Rules for jobs that should only run on feature branches (NOT on merge to master)
  test_jobs_rules: &test_jobs_rules
    rules:
      # This rule prevents the job from running in the release pipeline triggered by a merge.
      - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch/
        when: never
      # This rule runs the job for all other branch commits.
      - if: $CI_COMMIT_BRANCH

  # Rules for jobs that should ONLY run on merge to the default branch
  release_jobs_rules: &release_jobs_rules
    rules:
      # This rule ensures the job ONLY runs when a merge commit is pushed to the default branch.
      # This is the fix for the original issue.
      - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch/

# ==========================================================================
# Default settings and global variables
# ==========================================================================
default:
  tags:
    - cipcustana

variables:
  DOCKER_IMAGE_NAME: "aidi/aidi-ta02"
  DOCKAR_IMAGE_NAME_CANON: "aidita02"
  DOCKER_IMAGE_PORT: "8080"
  MARVIN_URL_PREFIX: "component/aidita02"
  SRC_FOLDERS: "moniteur_belge_api,django_project"
  SRC_TEST_FOLDERS: "tests"
  COVERAGE_MIN_PC: 0
  ENABLE_NEXUS_IQ: "true"
  ENABLE_FORTIFY: "true"
  PUBLISH_GITLAB: "true"
  PUBLISH_DOCKER: "true"
  APP_NAME: "aidi"
  MARVIN_AP_CODE: "aidi-ta02"
  MARVIN_DEV_ENV: "dev-01"
  ENABLE_RELEASE_MARVIN: "true"
  APCODE: "AP85405"
  DESCRIPTION: "Public Data API"
  GIT_FETCH_EXTRA_FLAGS: "--depth 200"

stages:
  - test
  - release

# ==========================================================================
# Pipeline creation logic
# ==========================================================================
workflow:
  rules:
    # Rule 1: Run a pipeline for merges to the default branch (for releases).
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch/
    # Rule 2: Do NOT run a pipeline for any other commit to the default branch.
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: never
    # Rule 3: Do NOT run pipelines for tags.
    - if: $CI_COMMIT_TAG
      when: never
    # Rule 4: Run a pipeline for all other branches (e.g., feature branches).
    - if: $CI_COMMIT_BRANCH

# ==========================================================================
# Test Stage Jobs (run on feature branches)
# ==========================================================================
test_image:
  stage: test
  script:
    - DOCKER_BUILDKIT=1 docker build . -t ${DOCKER_IMAGE_NAME}:${CI_COMMIT_SHA}
    - echo ${DOCKER_IMAGE_NAME}:${CI_COMMIT_SHA}
  needs: []
  <<: *test_jobs_rules # Apply rules for test jobs

all_tests:
  stage: test
  image: p-3096-docker-local.artifactory-dogen.group.echonet/icpy/code-quality:uv
  script:
    # Determine the base branch for comparison (either merge request source or default branch)
    - '[[ -v CI_MERGE_REQUEST_SOURCE_BRANCH_NAME ]] && FROM_REF="$CI_MERGE_REQUEST_SOURCE_BRANCH_NAME" || FROM_REF="$CI_DEFAULT_BRANCH"'
    - git fetch origin $FROM_REF
    # Code quality checks
    - uv run --dev --no-cache pre-commit run --from-ref "origin/$FROM_REF" --to-ref HEAD --show-diff-on-failure
    - uv run --dev --no-cache ruff check --output-format=gitlab > gl-code-quality-report.json
    # Testing & code coverage
    - |
      uv run --group test --no-cache bash -c "
        coverage erase &&
        export DJANGO_SETTINGS_MODULE=django_project.settings.local &&
        python manage.py migrate &&
        coverage run -m pytest tests/unit tests/functional --junitxml=report_test.xml &&
        coverage report --fail-under=\"${COVERAGE_MIN_PC}\" &&
        coverage xml -i &&
        coverage html"
  artifacts:
    expire_in: 30 days
    reports:
      codequality: gl-code-quality-report.json
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
      junit: report_test.xml
    paths:
      - coverage.xml
      - report_test.xml
      - htmlcov/
  needs: []
  <<: *test_jobs_rules # Apply rules for test jobs

test_sonar:
  stage: test
  needs: []
  image: "${SONAR_SCANNER_IMAGE}"
  allow_failure: true
  script:
    - sonar-scanner -X
      -Dsonar.host.url=${CENTRAL_SONAR_URL}
      -Dsonar.login=${CENTRAL_SONAR_TOKEN}
      -Dsonar.projectKey=${MARVIN_AP_CODE}
      -Dsonar.projectName=${CI_PROJECT_ROOT_NAMESPACE,,}-${CI_PROJECT_NAME//_/-}
      -Dsonar.links.homepage=${CI_PROJECT_URL}
      -Dsonar.branch.name=${CI_COMMIT_REF_NAME}
      -Dsonar.sourceEncoding=UTF-8
      -Dsonar.projectVersion=$(cat next_version)
      -Dsonar.sources=$SRC_FOLDERS
      -Dsonar.tests=$SRC_TEST_FOLDERS
      -Dsonar.python.xunit.reportPath=report.xml
      -Dsonar.python.coverage.reportPaths=coverage.xml
      -Dsonar.python.pylint.reportPath=pylint-report.txt
      -Dsonar.scm.disabled=False
      -Dsonar.scm.provider=git
  <<: *test_jobs_rules # Apply rules for test jobs

# ==========================================================================
# Release Stage Jobs (run on merge to master)
# ==========================================================================
pre_release_last_check:
  stage: release
  image: p-3096-docker-local.artifactory-dogen.group.echonet/icpy/code-quality:uv
  script:
    # Final test run on the merged code before triggering the release
    - |
      uv run --group test --no-cache bash -c "
        export DJANGO_SETTINGS_MODULE=django_project.settings.local &&
        python manage.py migrate &&
        coverage run -m pytest tests/unit tests/functional"
  needs: []
  <<: *release_jobs_rules # Apply rules for release jobs

trigger_jenkins:
  stage: release
  script:
    - >
      set -xv &&
      wget -S --header='Content-Type: application/json' --post-data "{
          \"PROJECT\":\"$CI_PROJECT_PATH\",
          \"APPLICATION_CODE\":\"$APP_NAME\",
          \"ENABLE_NEXUS_IQ\":\"$ENABLE_NEXUS_IQ\",
          \"ENABLE_FORTIFY\":\"$ENABLE_FORTIFY\",
          \"PUBLISH_GITLAB\":\"$PUBLISH_GITLAB\",
          \"PUBLISH_DOCKER\":\"$PUBLISH_DOCKER\",
          \"APP_NAME\":\"$APP_NAME\",
          \"MARVIN_AP_CODE\":\"$MARVIN_AP_CODE\",
          \"APCODE\":\"$APCODE\",
          \"DESCRIPTION\":\"$DESCRIPTION\",
          \"MARVIN_DEV_ENV\":\"$MARVIN_DEV_ENV\",
          \"ENABLE_RELEASE_MARVIN\":\"$ENABLE_RELEASE_MARVIN\"
        }" $JENKINS_URL/generic-webhook-trigger/invoke?token=$JENKINS_MARVIN_TOKEN
  needs:
    - pre_
