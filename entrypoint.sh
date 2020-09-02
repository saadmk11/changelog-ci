#!/bin/bash

set -e

git config user.name ${USERNAME}
git config user.email ${EMAIL}

python changelog-ci.py

git add .
git commit -m "Added Changelog"
git push origin ${GITHUB_REF}
