#!/bin/bash

git fetch --prune --unshallow origin ${GITHUB_HEAD_REF}
git checkout ${GITHUB_HEAD_REF}

python /scripts/changelog-ci.py

git config user.name ${INPUT_COMMITTER_USERNAME}
git config user.email ${INPUT_COMMITTER_EMAIL}

git add ${INPUT_CHANGELOG_FILENAME}
git commit -m "Add Changelog [ci skip]"
git push -u origin ${GITHUB_HEAD_REF}
