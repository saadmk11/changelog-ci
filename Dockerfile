FROM python:3.7

LABEL "com.github.actions.name"="Changelog CI"
LABEL "com.github.actions.description"="This is an action that commits on a release pull request with the changelog"
LABEL "com.github.actions.icon"="clock"
LABEL "com.github.actions.color"="blue"

LABEL "repository"="https://github.com/saadmk11/changelog-ci"
LABEL "homepage"="https://github.com/saadmk11/changelog-ci"
LABEL "maintainer"="saadmk11"

COPY requirements.txt /requirements.txt
COPY changelog.py /changelog.py

RUN pip install -r requirements.txt

ENTRYPOINT ["python", "-m", "changelog"]
