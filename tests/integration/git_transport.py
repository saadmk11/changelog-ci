"""Route test-only SSH Git commands to a local bare repository."""

import os
import shlex
import subprocess
import sys

if __name__ == "__main__":
    command = shlex.split(sys.argv[-1])[0]
    if command not in {"git-upload-pack", "git-receive-pack"}:
        raise ValueError("Unexpected Git transport command")
    if command == "git-receive-pack" and os.environ.get("_CHANGELOG_CI_TEST_DENY_PUSH"):
        raise SystemExit(1)
    raise SystemExit(
        subprocess.run(
            [command, os.environ["_CHANGELOG_CI_TEST_REMOTE"]], check=False
        ).returncode
    )
