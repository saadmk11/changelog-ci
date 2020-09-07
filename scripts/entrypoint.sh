#!/bin/bash

git fetch --prune --unshallow
git checkout ${GITHUB_HEAD_REF}

python /scripts/changelog-ci.py

git config user.name ${INPUT_COMMITER_USERNAME}
git config user.email ${INPUT_COMMITER_EMAIL}

git add ${INPUT_CHANGELOG_FILENAME}
git commit -m "Added Changelog"
git push -u --force origin HEAD:${GITHUB_HEAD_REF}
