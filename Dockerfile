FROM python:3.8

LABEL "com.github.actions.name"="Changelog PR"
LABEL "com.github.actions.description"="Changelog PR is a GitHub Action that generates changelog, Then the changelog is committed to the release Pull request."
LABEL "com.github.actions.icon"="clock"
LABEL "com.github.actions.color"="blue"

LABEL "repository"="https://github.com/JonathanAquino/changelog-pr"
LABEL "homepage"="https://github.com/JonathanAquino/changelog-pr"
LABEL "maintainer"="JonathanAquino"

COPY requirements.txt /requirements.txt

RUN pip install -r requirements.txt

COPY changelog-pr.py /changelog-pr.py

RUN ["chmod", "+x", "/changelog-pr.py"]
ENTRYPOINT ["python", "/changelog-pr.py"]
