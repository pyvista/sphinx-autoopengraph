"""Tests for the ``sphinx_autoopengraph`` Sphinx extension."""

from __future__ import annotations

import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import types

from docutils import nodes
import pytest

from sphinx_autoopengraph._description import _is_skipped
from sphinx_autoopengraph._description import _truncate
from sphinx_autoopengraph._image import _is_sphinx_gallery_document

TINYPAGES_DIR = Path(__file__).parent / 'tinypages'

_META_TAG = re.compile(r'<meta\b[^>]*>')
_META_KEY = re.compile(r'\b(?:property|name)="([^"]+)"')
_META_CONTENT = re.compile(r'\bcontent="([^"]*)"')

OPENGRAPH_SITE_URL = 'https://docs.example.org/'
OPENGRAPH_FALLBACK_IMAGE = f'{OPENGRAPH_SITE_URL}_static/fallback.png'


def copy_tinypages(tmp_path: Path) -> Path:
    """Return a throwaway copy of the ``tinypages`` project.

    Sphinx-Gallery generates its ``gallery`` pages into the source tree, so the
    checked-in project is never built in place.
    """
    source_dir = tmp_path / 'tinypages'
    shutil.rmtree(source_dir, ignore_errors=True)
    shutil.copytree(
        TINYPAGES_DIR,
        source_dir,
        ignore=shutil.ignore_patterns('__pycache__', '_build', 'gallery'),
    )
    return source_dir


def meta_tags(page: Path) -> dict[str, str]:
    """Return a built page's ``<meta>`` tags, keyed by ``property`` or ``name``.

    The HTML theme rewrites pages with an HTML parser, which does not preserve the
    order attributes were written in, so the tags cannot be matched as plain text.
    """
    tags: dict[str, str] = {}
    for tag in _META_TAG.findall(page.read_text(encoding='utf-8')):
        key = _META_KEY.search(tag)
        content = _META_CONTENT.search(tag)
        if key is not None and content is not None:
            tags.setdefault(key.group(1), html.unescape(content.group(1)))
    return tags


def _sphinx_build_cmd(
    source_dir: Path,
    html_dir: Path,
    doctree_dir: Path | None = None,
    sphinx_args: tuple[str, ...] = (),
) -> list[str]:
    """Create a sphinx-build command."""
    cmd = [sys.executable, '-msphinx', '-W', '-b', 'html', *sphinx_args]
    if doctree_dir is not None:
        cmd.extend(['-d', str(doctree_dir)])
    cmd.extend([str(source_dir), str(html_dir)])
    return cmd


def _run_sphinx_build(cmd: list[str]) -> tuple[int, str, str]:
    """Run sphinx-build and return returncode, stdout, and stderr."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env={**os.environ, 'MPLBACKEND': ''},
        encoding='utf8',
    )
    out, err = proc.communicate()
    return proc.returncode, out, err


def _append(path: Path, text: str) -> None:
    with path.open('a', encoding='utf-8') as file:
        file.write(text)


def _build_tinypages(tmp_path: Path, conf_extra: str = '') -> tuple[Path, int, str, str]:
    """Build the ``tinypages`` project and return its html dir and build result."""
    source_dir = copy_tinypages(tmp_path)
    if conf_extra:
        _append(source_dir / 'conf.py', f'\n{conf_extra}\n')
    html_dir = tmp_path / 'html'
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, html_dir, tmp_path / 'doctrees'),
    )
    return html_dir, returncode, out, err


def test_tinypages_builds_clean(tmp_path: Path):
    _, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'


def test_image_selection_picks_the_chosen_image(tmp_path: Path):
    """``some_images.rst`` selects image 2 explicitly."""
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'some_images.html')
    assert tags.get('og:image') == 'https://docs.example.org/_static/two.png'


def test_pages_with_no_images_keep_the_site_wide_default(tmp_path: Path):
    """A page with no images at all (``some_autodocs.html``) keeps ``ogp_image``."""
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'some_autodocs.html')
    assert tags.get('og:image') == OPENGRAPH_FALLBACK_IMAGE


def test_description_reaches_past_the_autodoc_admonition(tmp_path: Path):
    """Sphinx wraps autodoc output in an admonition-like node; our parser reaches in."""
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    description = meta_tags(html_dir / 'some_autodocs.html').get('og:description')
    assert description is not None
    assert description.startswith(
        'Return the answer to life, the universe, and everything. This second '
        'paragraph is what a plain text walk of the page would miss.'
    )


def test_plain_meta_description_matches_og_description(tmp_path: Path):
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'some_autodocs.html')
    assert tags.get('description') == tags.get('og:description')


def test_gallery_thumbnail_defaults_to_first_image(tmp_path: Path):
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'gallery' / 'plot_default.html')
    assert tags.get('og:image') == f'{OPENGRAPH_SITE_URL}_images/sphx_glr_plot_default_001.png'


def test_gallery_thumbnail_follows_sphinx_gallery_thumbnail_number(tmp_path: Path):
    """The full resolution image is used, not the gallery's own small thumbnail file."""
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'gallery' / 'plot_custom.html')
    assert tags.get('og:image') == f'{OPENGRAPH_SITE_URL}_images/sphx_glr_plot_custom_002.png'


def test_gallery_thumbnail_follows_sphinx_gallery_thumbnail_path(tmp_path: Path):
    """A ``sphinx_gallery_thumbnail_path`` selection has no full resolution image.

    Unlike ``sphinx_gallery_thumbnail_number``, which points at one of the
    example's own rendered figures, ``thumbnail_path`` points at a file that was
    never one of them, so there is no full-resolution version on the page to
    prefer -- the gallery's own (small) thumbnail file is the only image there is.
    """
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'gallery' / 'plot_thumbnail_path.html')
    assert tags.get('og:image') == (
        f'{OPENGRAPH_SITE_URL}_images/sphx_glr_plot_thumbnail_path_thumb.png'
    )


def test_gallery_description_uses_the_examples_own_introduction(tmp_path: Path):
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'gallery' / 'plot_custom.html')
    assert tags.get('og:description', '').startswith(
        'Draw a rising line and then a falling one, and pick the second as the thumbnail.'
    )
    assert 'Download' not in tags.get('og:description', '')
    assert 'Total running time' not in tags.get('og:description', '')
    assert 'Gallery generated by' not in tags.get('og:description', '')


def test_description_excludes_a_download_only_paragraph(tmp_path: Path):
    """A paragraph of nothing but download links contributes no text at all.

    Mirrors the shape Sphinx-Gallery's own download admonition and
    ``sphinx-examples-as-code``'s replacement download links both produce: a
    paragraph whose only content is one or more ``download_reference`` nodes,
    with just separators (here, " | ") between them. Both are already excluded
    as a *node type* (``download_reference`` is always skipped, regardless of
    surrounding structure), so this holds regardless of which extension built
    the paragraph -- ``download_links.rst`` does not depend on either one.
    """
    html_dir, returncode, out, err = _build_tinypages(tmp_path)
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    description = meta_tags(html_dir / 'download_links.html').get('og:description')
    assert description == (
        'The real prose introduction of this page, which should become the description.'
    )
    assert 'Download' not in description


def test_autoopengraph_thumbnail_rejected_in_gallery_example(tmp_path: Path):
    source_dir = copy_tinypages(tmp_path)
    _append(
        source_dir / 'gallery_src' / 'plot_default.py',
        '\n# %%\n# .. autoopengraph_thumbnail:: 4\n',
    )
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, tmp_path / 'html', tmp_path / 'doctrees'),
    )
    assert returncode != 0
    # The guidance keeps the number the author asked for
    assert '# sphinx_gallery_thumbnail_number = 4' in f'{out}\n{err}'


def test_autoopengraph_thumbnail_selected_twice_warns(tmp_path: Path):
    """A page has one link preview, so a second selection is reported and ignored."""
    source_dir = copy_tinypages(tmp_path)
    # ``some_images.rst`` already selects image 2
    _append(source_dir / 'some_images.rst', '\n.. autoopengraph_thumbnail:: 3\n')

    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, tmp_path / 'html', tmp_path / 'doctrees'),
    )
    # Only fatal because tinypages builds with ``-W``
    assert returncode != 0
    output = f'{out}\n{err}'
    assert 'already selects image 2' in output
    assert 'Ignoring this selection of image 3' in output


def test_autoopengraph_thumbnail_out_of_range_warns(tmp_path: Path):
    """Selecting an image the page does not have falls back to its first one."""
    source_dir = copy_tinypages(tmp_path)
    page = source_dir / 'some_images.rst'
    page.write_text(page.read_text(encoding='utf-8').replace(':: 2', ':: 999'))

    html_dir = tmp_path / 'html'
    returncode, out, err = _run_sphinx_build(
        # Without ``-W`` the warning does not end the build, so the fallback is observable
        _sphinx_build_cmd(source_dir, html_dir, tmp_path / 'doctrees', ('--keep-going',)),
    )
    assert returncode != 0  # ``--keep-going`` still reports the warning at the end
    assert "'autoopengraph_thumbnail' selects image 999" in f'{out}\n{err}'
    assert meta_tags(html_dir / 'some_images.html').get('og:image') == (
        'https://docs.example.org/_static/one.png'
    )


def test_autoopengraph_image_can_be_disabled(tmp_path: Path):
    """``autoopengraph_image = False`` leaves ``sphinxext-opengraph`` alone.

    Distinct from disabling ``sphinx_autoopengraph`` entirely: the description
    half stays on, only the image selection turns off.
    """
    html_dir, returncode, out, err = _build_tinypages(tmp_path, 'autoopengraph_image = False')
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'some_images.html')
    assert tags.get('og:image') == OPENGRAPH_FALLBACK_IMAGE
    assert 'og:description' in tags


def test_autoopengraph_description_can_be_disabled(tmp_path: Path):
    """``autoopengraph_description = False`` leaves ``sphinxext-opengraph`` alone.

    Distinct from disabling ``sphinx_autoopengraph`` entirely: the image half
    stays on, only the description parser turns off.
    """
    html_dir, returncode, out, err = _build_tinypages(tmp_path, 'autoopengraph_description = False')
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'some_autodocs.html')
    # Without our own parser, the admonition-like node hides the whole docstring
    assert 'og:description' not in tags
    assert 'og:image' in meta_tags(html_dir / 'some_images.html')


def test_requires_sphinxext_opengraph(tmp_path: Path):
    """Enabling ``sphinx_autoopengraph`` is a no-op without ``sphinxext.opengraph``.

    Listing ``sphinx_autoopengraph`` is itself the opt-in, so the only way to get
    nothing is to not also enable ``sphinxext.opengraph``.
    """
    source_dir = copy_tinypages(tmp_path)
    conf = source_dir / 'conf.py'
    conf.write_text(conf.read_text(encoding='utf-8').replace("'sphinxext.opengraph',\n", ''))

    html_dir = tmp_path / 'html'
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, html_dir, tmp_path / 'doctrees'),
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    assert 'og:image' not in meta_tags(html_dir / 'some_images.html')


def test_epub_builder_is_left_alone(tmp_path: Path):
    """``sphinxext-opengraph`` itself has no epub support, so neither does this.

    ``page_fields`` opts every page out before either half of this extension does
    anything, so an epub build with ``sphinx_autoopengraph`` enabled behaves exactly
    as it would without it. A minimal, locally-hosted project is built rather than
    ``tinypages``, whose remote-hosted images the epub builder tries (and, offline,
    fails) to download -- unrelated to what this test checks.
    """
    source_dir = _minimal_project(
        tmp_path,
        'Epub\n====\n\nSome real prose for the description.\n',
        conf_extra="epub_copyright = '2024'\nversion = release = '1.0'\n",
    )
    epub_dir = tmp_path / 'epub'
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, epub_dir, tmp_path / 'doctrees', ('-b', 'epub')),
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'


def _minimal_project(tmp_path: Path, index: str, conf_extra: str = '') -> Path:
    """Write a minimal single-page Sphinx project and return its source dir."""
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    (source_dir / 'conf.py').write_text(
        "extensions = ['sphinx_autoopengraph', 'sphinxext.opengraph']\n"
        "root_doc = 'index'\n"
        "ogp_site_url = 'https://docs.example.org/'\n" + conf_extra,
        encoding='utf-8',
    )
    (source_dir / 'index.rst').write_text(index, encoding='utf-8')
    return source_dir


def _build_minimal(tmp_path: Path, index: str, conf_extra: str = '') -> tuple[int, str, str, Path]:
    source_dir = _minimal_project(tmp_path, index, conf_extra)
    html_dir = tmp_path / 'html'
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, html_dir, tmp_path / 'doctrees'),
    )
    return returncode, out, err, html_dir


def test_invalid_thumbnail_argument_errors(tmp_path: Path):
    source_dir = copy_tinypages(tmp_path)
    _append(source_dir / 'some_autodocs.rst', '\n.. autoopengraph_thumbnail:: not-a-number\n')
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, tmp_path / 'html2', tmp_path / 'doctrees2'),
    )
    assert returncode != 0
    assert "expects an integer, got 'not-a-number'" in f'{out}\n{err}'


def test_zero_thumbnail_argument_errors(tmp_path: Path):
    source_dir = copy_tinypages(tmp_path)
    _append(source_dir / 'some_autodocs.rst', '\n.. autoopengraph_thumbnail:: 0\n')
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, tmp_path / 'html', tmp_path / 'doctrees'),
    )
    assert returncode != 0
    assert 'is one-based, so 0 is not a valid image number' in f'{out}\n{err}'


def test_explicit_og_image_field_is_not_overridden(tmp_path: Path):
    returncode, out, err, html_dir = _build_minimal(
        tmp_path,
        ':og:image: https://docs.example.org/_static/manual.png\n\n'
        'Explicit\n========\n\n'
        '.. image:: https://docs.example.org/_static/auto.png\n\n'
        'Some prose.\n',
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    assert meta_tags(html_dir / 'index.html').get('og:image') == (
        'https://docs.example.org/_static/manual.png'
    )


def test_explicit_og_description_field_is_not_overridden(tmp_path: Path):
    returncode, out, err, html_dir = _build_minimal(
        tmp_path,
        ':og:description: A hand-written description.\n\n'
        'Explicit\n========\n\n'
        'Some other prose that would otherwise become the description.\n',
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    assert meta_tags(html_dir / 'index.html').get('og:description') == (
        'A hand-written description.'
    )


def test_ogp_disable_field_opts_the_page_out_entirely(tmp_path: Path):
    returncode, out, err, html_dir = _build_minimal(
        tmp_path,
        ':ogp_disable:\n\n'
        'Disabled\n========\n\n'
        '.. image:: https://docs.example.org/_static/auto.png\n\n'
        'Some prose.\n',
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    tags = meta_tags(html_dir / 'index.html')
    assert 'og:image' not in tags
    assert 'og:description' not in tags


def test_page_with_no_prose_at_all_gets_no_description(tmp_path: Path):
    returncode, out, err, html_dir = _build_minimal(
        tmp_path,
        'No Prose\n========\n\n.. image:: https://docs.example.org/_static/auto.png\n',
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    assert 'og:description' not in meta_tags(html_dir / 'index.html')


def test_ogp_description_length_zero_disables_description(tmp_path: Path):
    returncode, out, err, html_dir = _build_minimal(
        tmp_path,
        'Zero Length\n============\n\nSome prose that would otherwise be a description.\n',
        conf_extra='ogp_description_length = 0\n',
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    assert 'og:description' not in meta_tags(html_dir / 'index.html')


def test_ogp_enable_meta_description_false_skips_plain_meta_tag(tmp_path: Path):
    returncode, out, err, html_dir = _build_minimal(
        tmp_path,
        'No Plain Meta\n==============\n\nSome real prose for the description.\n',
        conf_extra='ogp_enable_meta_description = False\n',
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    tags = meta_tags(html_dir / 'index.html')
    assert 'og:description' in tags
    assert 'description' not in tags


def test_invalid_per_page_description_length_falls_back_to_the_default(tmp_path: Path):
    """``ogp_description_length`` has no ``og:`` prefix, matching ``ogp_disable``."""
    returncode, out, err, html_dir = _build_minimal(
        tmp_path,
        ':ogp_description_length: not-a-number\n\n'
        'Invalid Override\n==================\n\n'
        'Some real prose for the description.\n',
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    assert meta_tags(html_dir / 'index.html').get('og:description') == (
        'Some real prose for the description.'
    )


def test_out_of_range_warning_is_suppressed_when_rendering_is_known_to_be_skipped(
    tmp_path: Path,
):
    """A soft dependency on PyVista's own config values, simulated without PyVista."""
    source_dir = copy_tinypages(tmp_path)
    page = source_dir / 'some_images.rst'
    page.write_text(page.read_text(encoding='utf-8').replace(':: 2', ':: 999'))
    _append(
        source_dir / 'conf.py',
        "\ndef setup(app):\n    app.add_config_value('pyvista_plot_skip', True, 'html')\n",
    )

    html_dir = tmp_path / 'html'
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, html_dir, tmp_path / 'doctrees'),
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'
    assert 'selects image 999' not in f'{out}\n{err}'


def test_works_without_any_plot_generating_extension(tmp_path: Path):
    """Nothing here needs a plot directive, or even a locally-hosted image."""
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    (source_dir / 'conf.py').write_text(
        "extensions = ['sphinx_autoopengraph', 'sphinxext.opengraph']\n"
        "root_doc = 'index'\n"
        "ogp_site_url = 'https://docs.example.org/'\n",
        encoding='utf-8',
    )
    (source_dir / 'index.rst').write_text(
        'Standalone\n==========\n\n'
        '.. image:: https://docs.example.org/_static/photo.png\n\n'
        'A plain page with an ordinary image and its own leading prose.\n',
        encoding='utf-8',
    )

    html_dir = tmp_path / 'html'
    returncode, out, err = _run_sphinx_build(
        _sphinx_build_cmd(source_dir, html_dir, tmp_path / 'doctrees'),
    )
    assert returncode == 0, f'sphinx build failed with stdout:\n{out}\nstderr:\n{err}\n'

    tags = meta_tags(html_dir / 'index.html')
    assert tags.get('og:image') == 'https://docs.example.org/_static/photo.png'
    assert tags.get('og:description') == (
        'A plain page with an ordinary image and its own leading prose.'
    )


def test_is_skipped_treats_a_bare_text_node_as_furniture():
    """Defensive: both call sites already special-case ``Text`` before calling this.

    ``_prose_paragraphs`` never recurses into a paragraph's children, and
    ``_prose_text`` yields ``Text`` directly without calling ``_is_skipped`` on it,
    so this is never reached through either of them -- checked directly here so a
    future caller that does not already special-case ``Text`` still gets the right
    answer instead of an ``AttributeError`` from ``.get('classes', ...)``.
    """
    assert _is_skipped(nodes.Text('some text')) is True


def test_is_sphinx_gallery_document_accepts_a_bare_gallery_dirs_string(tmp_path: Path):
    """``gallery_dirs`` is normally a list, but Sphinx-Gallery also accepts one string."""
    app = types.SimpleNamespace(
        config=types.SimpleNamespace(sphinx_gallery_conf={'gallery_dirs': 'gallery'}),
    )
    assert _is_sphinx_gallery_document(app, 'gallery/plot_default') is True
    assert _is_sphinx_gallery_document(app, 'some_autodocs') is False


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('short enough', 'short enough'),
        ('exactly twenty chars', 'exactly twenty chars'),
        # Backs up to a word boundary rather than cutting mid-word
        ('a sentence that runs on and on', 'a sentence that...'),
        # A single long word has no boundary to back up to
        ('supercalifragilisticexpialidocious', 'supercalifragilis...'),
        # Trailing punctuation left dangling by the cut is dropped
        ('one, two, three, four', 'one, two, three...'),
    ],
)
def test_truncate(text: str, expected: str):
    assert _truncate(text, 20) == expected
