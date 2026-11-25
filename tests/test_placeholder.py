"""Smoke test: the interpreter is the pinned one and the source package imports."""

import sys

import src


def test_python_version_is_pinned() -> None:
    assert sys.version_info[:2] == (3, 11)


def test_source_package_imports() -> None:
    assert src.__doc__
