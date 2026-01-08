import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_DOCS_BUILT = False


class MkDocsBuildHook(BuildHookInterface):
    PLUGIN_NAME = "mkdocs"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.__command: list[str] | None = None

    @property
    def command(self) -> list[str]:
        if self.__command is None:
            raw_command = self.config.get("command")
            if raw_command is None:
                self.__command = [sys.executable, "-m", "mkdocs", "build"]
            else:
                if not isinstance(raw_command, list):
                    raise TypeError(
                        "Option `command` for build hook `mkdocs` must be an array of strings"
                    )
                if not raw_command:
                    raise ValueError(
                        "Option `command` for build hook `mkdocs` must not be empty"
                    )
                if not all(isinstance(part, str) for part in raw_command):
                    raise TypeError(
                        "All entries in `command` for build hook `mkdocs` must be strings"
                    )
                self.__command = raw_command
        return self.__command

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:  # noqa: ARG002
        global _DOCS_BUILT
        if _DOCS_BUILT:
            return

        # The Dockerfile installs the package from a reduced set of files and
        # does not include documentation sources. In that scenario (or when
        # explicitly disabled), skip building docs rather than failing the build.
        if os.environ.get("FDC3_SKIP_DOCS_BUILD", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            _DOCS_BUILT = True
            return

        mkdocs_config = Path(self.root) / "mkdocs.yml"
        docs_dir = Path(self.root) / "documentation"
        if not mkdocs_config.exists() or not docs_dir.exists():
            _DOCS_BUILT = True
            return

        subprocess.run(self.command, cwd=self.root, check=True)
        _DOCS_BUILT = True


def get_build_hook():
    return MkDocsBuildHook
