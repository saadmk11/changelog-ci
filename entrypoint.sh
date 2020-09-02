#!/bin/sh

set -e

echo ${GITHUB_REF}
echo ${GITHUB_EVENT_PATH}
echo ${GITHUB_REPOSITORY}
echo ${INPUT_CHANGELOG_FILENAME}

git config user.name ${secrets.USERNAME}
git config user.email ${secrets.EMAIL}

python changeolg-ci

git add .
git commit -m "Added Changelog"
git push origin ${GITHUB_REF}
