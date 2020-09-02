#!/bin/bash

git config user.name ${USERNAME}
git config user.email ${EMAIL}

git fetch --prune --unshallow
git checkout ${GITHUB_HEAD_REF}

python /scripts/changelog-ci.py

git add .
git commit -m "Added Changelog"
git push -u --force origin HEAD:${GITHUB_HEAD_REF}
