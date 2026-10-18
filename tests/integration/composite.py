"""Exercise the installed composite against a local HTTPS GitHub substitute."""

import json
import os
import shlex
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import certifi
import yaml


def serve(directory: Path) -> None:
    """Serve test GitHub API responses."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            if self.headers.get("Authorization") != "Bearer test-token":
                self.send_error(401)
                return
            if self.path.startswith("/search/issues"):
                payload: object = {
                    "total_count": 1,
                    "incomplete_results": False,
                    "items": [
                        {
                            "number": 1,
                            "title": "Fix café 🐛\n::error::literal text",
                            "html_url": "https://github.com/owner/repo/pull/1",
                            "labels": [],
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                }
            elif self.path == "/repos/owner/repo/releases/latest":
                payload = {"published_at": "2026-01-01T00:00:00Z"}
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_POST(self) -> None:
            scenario = (directory / "scenario").read_text()
            expected = {
                "comment": "/repos/owner/repo/issues/9/comments",
                "dispatch": "/repos/owner/repo/pulls",
            }.get(scenario)
            if self.headers.get("Authorization") != "Bearer test-token":
                self.send_error(401)
                return
            if self.path != expected:
                self.send_error(403)
                return
            data = self.rfile.read(int(self.headers["Content-Length"]))
            (directory / "mutation.json").write_bytes(data)
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"number":9,"html_url":"https://github.com/owner/repo/pull/9"}'
            )

    server = HTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(directory / "cert.pem", directory / "key.pem")
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    (directory / "port").write_text(str(server.server_port))
    server.serve_forever()


def prepare(root: Path, directory: Path, scenario: str = "comment") -> None:
    """Prepare a composite test with the built wheel and local API."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "port").unlink(missing_ok=True)
    (directory / "mutation.json").unlink(missing_ok=True)
    (directory / "scenario").write_text(scenario)
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(directory / "key.pem"),
            "-out",
            str(directory / "cert.pem"),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        env={**os.environ, "MSYS_NO_PATHCONV": "1"},
    )
    (directory / "trust.pem").write_bytes(
        Path(certifi.where()).read_bytes() + (directory / "cert.pem").read_bytes()
    )
    with (directory / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.integration.composite",
                "serve",
                str(directory),
            ],
            cwd=root,
            stdout=log,
            stderr=log,
        )
    (directory / "pid").write_text(str(process.pid))
    for _ in range(100):
        if (directory / "port").exists():
            break
        if process.poll() is not None:
            raise RuntimeError("Mock HTTPS server failed to start")
        time.sleep(0.05)
    else:
        process.terminate()
        raise RuntimeError("Mock HTTPS server did not become ready")
    event: dict[str, object] = {
        "repository": {"full_name": "owner/repo", "default_branch": "main"}
    }
    if scenario != "dispatch":
        event["number"] = 9
        event["pull_request"] = {
            "title": "Release v2.0.2",
            "head": {"ref": "release", "repo": {"full_name": "owner/repo"}},
            "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
        }
    (directory / "event.json").write_text(json.dumps(event))
    meta = yaml.safe_load((root / "action.yaml").read_text())
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    wheel = root / "dist" / f"gh_changelog_ci-{version}-py3-none-any.whl"
    invoke = meta["runs"]["steps"][-1]
    # Substitute the wheel and runner context; retain the composite command.
    invoke["run"] = invoke["run"].replace(
        f"gh-changelog-ci[actions]=={version}", wheel.as_uri() + "[actions]"
    )
    runner_context = {
        "GITHUB_API_URL": f"https://127.0.0.1:{(directory / 'port').read_text()}",
        "GITHUB_EVENT_PATH": str(directory / "event.json"),
        "GITHUB_EVENT_NAME": "workflow_dispatch"
        if scenario == "dispatch"
        else "pull_request",
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_BASE_REF": "" if scenario == "dispatch" else "main",
        "GITHUB_HEAD_REF": "" if scenario == "dispatch" else "release",
        "GITHUB_REF": "refs/heads/main"
        if scenario == "dispatch"
        else "refs/pull/9/merge",
    }
    invoke["env"]["SSL_CERT_FILE"] = str(directory / "trust.pem")
    workspace = directory / "consumer"
    if scenario == "comment":
        workspace.mkdir(exist_ok=True)
        (workspace / "legacy.json").write_bytes(
            (root / "tests/fixtures/legacy/comment.json").read_bytes()
        )
    else:
        from tests.git import command

        remote = directory / "remote.git"
        seed = directory / "seed"
        command(directory, "init", "--bare", "--initial-branch=main", str(remote))
        command(directory, "init", "--initial-branch=main", str(seed))
        (seed / "CHANGELOG.md").write_text("Base changelog\n")
        command(seed, "add", "CHANGELOG.md")
        command(seed, "commit", "-m", "Base")
        command(seed, "checkout", "-b", "release")
        (seed / "CHANGELOG.md").write_text("Head changelog\n")
        command(seed, "commit", "-am", "Release head")
        command(seed, "checkout", "main")
        command(seed, "remote", "add", "origin", remote.as_uri())
        command(seed, "push", "origin", "main", "release")
        command(directory, "clone", "--depth=1", remote.as_uri(), str(workspace))
        command(workspace, "checkout", "--detach")
        command(
            workspace, "remote", "set-url", "origin", "git@127.0.0.1:owner/repo.git"
        )
        invoke["env"].update(
            {
                "GIT_SSH_COMMAND": shlex.join(
                    [
                        Path(sys.executable).as_posix(),
                        (root / "tests/integration/git_transport.py").as_posix(),
                    ]
                ),
                "GIT_SSH_VARIANT": "simple",
                "_CHANGELOG_CI_TEST_REMOTE": str(remote),
            }
        )
    runner_context["GITHUB_WORKSPACE"] = str(workspace)
    # GitHub replaces reserved step env values before launching the shell.
    invoke["run"] = (
        "\n".join(
            f"export {key}={shlex.quote(value)}"
            for key, value in runner_context.items()
        )
        + "\n"
        + invoke["run"]
    )
    (directory / "action.yaml").write_text(
        yaml.safe_dump(meta, sort_keys=False, width=1000)
    )


def verify(directory: Path) -> None:
    """Check the generated file and API mutations for this scenario."""
    scenario = (directory / "scenario").read_text()
    if scenario == "pr":
        assert not (directory / "mutation.json").exists()
    if scenario in {"comment", "dispatch"}:
        body = json.loads((directory / "mutation.json").read_text())["body"]
        version = "1.0.0" if scenario == "dispatch" else "v2.0.2"
        assert body.startswith(f"# Version: {version}\n\n")
        assert "Fix café 🐛" in body and "\n::error::literal text" in body
    if scenario != "comment":
        from tests.git import command

        branch = command(directory / "consumer", "branch", "--show-current")
        content = command(directory / "remote.git", "show", f"{branch}:CHANGELOG.md")
        assert "Fix café 🐛" in content
        assert content.endswith(
            "Base changelog" if scenario == "dispatch" else "Head changelog"
        )
    print(f"Candidate composite {scenario} flow passed.")


def exercise(root: Path, directory: Path) -> None:
    """Run the composite command and check its outputs."""
    metadata = yaml.safe_load((directory / "action.yaml").read_text())
    step = metadata["runs"]["steps"][-1]
    env = dict(os.environ)
    for key, value in step["env"].items():
        if key.startswith("INPUT_"):
            default = metadata["inputs"][key[6:].lower()].get("default", "")
            env[key] = default if isinstance(default, str) else str(default)
        elif not value.startswith("${{"):
            env[key] = value
    env.update(
        {
            "GITHUB_ACTIONS": "true",
            "INPUT_CONFIG_FILE": "legacy.json"
            if (directory / "scenario").read_text() == "comment"
            else "",
            "INPUT_RELEASE_VERSION": "1.0.0",
            "INPUT_GITHUB_TOKEN": "test-token",
            "CHANGELOG_CI_UV": str(
                Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
            ),
            "UV_EXTRA_INDEX_URL": "https://invalid.example/simple",
            "PYTHONPATH": "does-not-exist",
        }
    )
    with tempfile.TemporaryDirectory(prefix="changelog-ci-composite-") as temporary:
        env.update(
            {
                "RUNNER_TEMP": temporary,
                "GITHUB_OUTPUT": str(Path(temporary) / "output"),
                # The runner injects its context after applying step env.
                "GITHUB_API_URL": "https://127.0.0.1:1",
                "GITHUB_EVENT_PATH": str(Path(temporary) / "runner-event.json"),
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_REPOSITORY": "runner/repository",
                "GITHUB_BASE_REF": "runner-base",
                "GITHUB_HEAD_REF": "runner-head",
                "GITHUB_REF": "refs/pull/123/merge",
                "GITHUB_WORKSPACE": temporary,
            }
        )
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", step["run"]],
            cwd=temporary,
            env=env,
            check=True,
        )
        output = Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8")
        version = (
            "1.0.0" if (directory / "scenario").read_text() == "dispatch" else "v2.0.2"
        )
        values: dict[str, str] = {}
        lines = iter(output.splitlines())
        for header in lines:
            key, separator, delimiter = header.partition("<<")
            assert separator, "Unexpected output format"
            content: list[str] = []
            for line in lines:
                if line == delimiter:
                    break
                content.append(line)
            else:
                raise AssertionError("Unterminated output value")
            values[key] = "\n".join(content)
        assert f"Version: {version}%0A" in values["changelog"]
        assert values["changed"] == "true"
        assert values["changelog-file"] == "CHANGELOG.md"
        created = (directory / "scenario").read_text() == "dispatch"
        assert values["pull-request-number"] == ("9" if created else "")
        assert values["pull-request-url"] == (
            "https://github.com/owner/repo/pull/9" if created else ""
        )
    verify(directory)


def stop(directory: Path) -> None:
    """Stop the test server if setup reached the server-start phase."""
    if (directory / "pid").exists():
        with suppress(ProcessLookupError):
            os.kill(int((directory / "pid").read_text()), signal.SIGTERM)


if __name__ == "__main__":
    operation = sys.argv[1]
    target = Path(sys.argv[2]).resolve()
    if operation == "serve":
        serve(target)
    elif operation == "prepare":
        prepare(Path.cwd(), target, sys.argv[3] if len(sys.argv) > 3 else "comment")
    elif operation == "verify":
        verify(target)
    elif operation == "exercise":
        exercise(Path.cwd(), target)
    elif operation == "stop":
        stop(target)
    else:
        raise ValueError("Unknown harness operation")
