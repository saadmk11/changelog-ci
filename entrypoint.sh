#!/bin/bash

set -e

git config user.name ${USERNAME}
git config user.email ${EMAIL}
echo "START"
python changelog-ci.py
echo "END"
git add .
git commit -m "Added Changelog"
git push origin ${GITHUB_REF}
