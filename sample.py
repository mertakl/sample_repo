##Can you refactor and streamline? Also pre_release does not seem to be triggered when merged. Can you fix?

default:
  tags:
    - cipcustana
# You can override the included template(s) by including variable overrides
# SAST customization: https://docs.gitlab.com/ee/user/application_security/sast/#customizing-the-sast-settings
# Secret Detection customization: https://docs.gitlab.com/ee/user/application_security/secret_detection/#customizing-settings
# Dependency Scanning customization: https://docs.gitlab.com/ee/user/application_security/dependency_scanning/#customizing-the-dependency-scanning-settings
# Container Scanning customization: https://docs.gitlab.com/ee/user/application_security/container_scanning/#customizing-the-container-scanning-settings
# Note that environment variables can be set in several places
# See https://docs.gitlab.com/ee/ci/variables/#cicd-variable-precedence
variables:
  DOCKER_IMAGE_NAME: "aidi/aidi-ta02"
  DOCKER_IMAGE_NAME_CANON: "aidita02"
  DOCKER_IMAGE_PORT: "8080"
  MARVIN_URL_PREFIX: "component/aidita02"
  # comma separated list of folders containing source code for analysis
  SRC_FOLDERS: "moniteur_belge_api,django_project"
  # comma seperated list of folders containing source code for tests
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

workflow:
  rules:
    # no pipeline for commit tag
    - if: $CI_COMMIT_TAG
      when: never
    # runs if merging to master
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch/
    # don't run on master (except if it's merging)
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: never
    # run on branches
    - if: $CI_COMMIT_BRANCH


test_image:
  stage: test
  script:
    - DOCKER_BUILDKIT=1 docker build . -t ${DOCKER_IMAGE_NAME}:${CI_COMMIT_SHA}
    - echo ${DOCKER_IMAGE_NAME}:${CI_COMMIT_SHA}
  needs: [ ]
  rules:
    # don't run on master during merging
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch/
      when: never
    # run on branches
    - if: $CI_COMMIT_BRANCH

all_tests:
  stage: test
  image: p-3096-docker-local.artifactory-dogen.group.echonet/icpy/code-quality:uv
  script:
    #code quality
    - '[[ -v CI_MERGE_REQUEST_SOURCE_BRANCH_NAME ]] && FROM_REF="$CI_MERGE_REQUEST_SOURCE_BRANCH_NAME" || FROM_REF="$CI_DEFAULT_BRANCH"'
    - git fetch origin $FROM_REF
    - uv run --dev --no-cache pre-commit run --from-ref "origin/$FROM_REF" --to-ref HEAD --show-diff-on-failure
    - uv run --dev --no-cache ruff check --output-format=gitlab > gl-code-quality-report.json

    #testing & code coverage
    - echo "The current branch is $FROM_REF"
    - uv run --group test --no-cache bash -c "
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
      - report.xml
      - report.html
      - htmlcov/
      - pylint-report.txt
  needs: []
  rules:
      # don't run on master during merging
      - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch/
        when: never
      # run on branches
      - if: $CI_COMMIT_BRANCH

test_sonar:
  stage: test
  needs: [ ]
  image: "${SONAR_SCANNER_IMAGE}"
  allow_failure: true
  before_script: # to override the global before_script
    - 'true'
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
  rules:
      # don't run on master during merging
      - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_MESSAGE =~ /^Merge branch/
        when: never
      # run on branches
      - if: $CI_COMMIT_BRANCH


pre_release_last_check:
  stage: release
  image: p-3096-docker-local.artifactory-dogen.group.echonet/icpy/code-quality:uv
  script:
    #code quality
    - FROM_REF=$CI_DEFAULT_BRANCH
    - echo "The current branch is $(git branch --show-current)"
    - git fetch origin $FROM_REF
    # last testing before release after the merge
    - uv run --group test --no-cache bash -c "
      export DJANGO_SETTINGS_MODULE=django_project.settings.local &&
      python manage.py migrate &&
      coverage run -m pytest tests/unit tests/functional"
  needs: [ ]
  only:
    - master

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
  only:
    - master
  needs:
    - pre_release_last_check
#  needs:
#    - job: semantic_release
