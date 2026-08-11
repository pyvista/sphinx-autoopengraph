"""Sphinx config for testing."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

project = 'tinypages'
root_doc = 'index'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx_autoopengraph',
    'sphinx_gallery.gen_gallery',
    'sphinxext.opengraph',
]

exclude_patterns = ['_build', 'gallery_src']

html_theme = 'basic'

# -- Sphinx-Gallery ---------------------------------------------------------
# ``gallery_dirs`` is generated into the source tree, so tests build from a copy.
sphinx_gallery_conf = {
    'examples_dirs': ['gallery_src'],
    'gallery_dirs': ['gallery'],
    'filename_pattern': r'\.py',
    'image_scrapers': ('matplotlib',),
    'download_all_examples': False,
    'remove_config_comments': True,
}

# -- Open Graph ---------------------------------------------------------------
# No configuration of ``sphinx_autoopengraph`` itself is required; ``ogp_site_url``
# is the only thing ``sphinxext-opengraph`` requires to emit absolute URLs.
ogp_site_url = 'https://docs.example.org/'
ogp_image = 'https://docs.example.org/_static/fallback.png'
