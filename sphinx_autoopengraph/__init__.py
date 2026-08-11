"""Automatic Open Graph link previews for Sphinx documentation. See the README."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import _description
from . import _image
from ._version import __version__

if TYPE_CHECKING:
    from sphinx.application import Sphinx


def setup(app: Sphinx) -> dict[str, bool | str]:
    """Set up automatic Open Graph link previews.

    Returns
    -------
    dict[str, bool | str]
        Sphinx extension metadata.

    """
    _image.setup(app)
    _description.setup(app)
    return {
        'parallel_read_safe': True,
        'parallel_write_safe': True,
        'version': __version__,
    }
