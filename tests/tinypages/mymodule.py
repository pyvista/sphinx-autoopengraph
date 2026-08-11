"""A tiny module used to test description extraction from autodoc output."""

from __future__ import annotations


def documented_function() -> int:
    """Return the answer to life, the universe, and everything.

    This second paragraph is what a plain text walk of the page would miss.
    Sphinx wraps autodoc output in a node that subclasses
    ``docutils.nodes.Admonition``, and a walker that skips admonitions (as
    ``sphinxext-opengraph``'s own does) never reaches either paragraph.
    """
    return 42
