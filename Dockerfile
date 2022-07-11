FROM python:3.10

LABEL "com.github.actions.name"="Changelog CI"
LABEL "com.github.actions.description"="Changelog CI is a GitHub Action that generates changelog, Then the changelog is committed and/or commented to the release Pull request."
LABEL "com.github.actions.icon"="clock"
LABEL "com.github.actions.color"="blue"

LABEL "repository"="https://github.com/saadmk11/changelog-ci"
LABEL "homepage"="https://github.com/saadmk11/changelog-ci"
LABEL "maintainer"="saadmk11"

COPY ./requirements.txt .

RUN pip install -r requirements.txt

COPY ./scripts ./scripts

CMD ["python", "-m", "scripts.main"]
