"""Open Graph images chosen by position, independent of what rendered them.

This is not specific to any plot-generating extension: it numbers every
*locally rendered* image on a page -- in document order, regardless of whether a
plot directive, a plain ``.. image::``, or anything else produced it -- and lets a
page point at the one it wants as its ``og:image``. The default is the first
image, which is what most pages want without any selection at all. Externally
hosted images (badges, shields, sponsor logos, ...) are never candidates, default
or explicitly selected; see :func:`_image_nodes`.

Sphinx-Gallery pages are handled separately, since they already have a thumbnail:
their ``og:image`` always matches the gallery's own selection, using the full
resolution version of it rather than the (too small to preview well) thumbnail file
Sphinx-Gallery renders.

The result is written to the page's ``og:image`` field before ``sphinxext-opengraph``
renders its tags, so its own default (``ogp_image``) is only ever used as a fallback
for pages with no image of their own -- this includes the site's root page. A
project whose front page has its own images (a common shape: a landing page with
inline example plots below the fold) will get one of *those* as its preview, not
``ogp_image``, unless that page opts out with ``.. autoopengraph_thumbnail:: none``
(see :class:`OpenGraphThumbnailDirective`). ``ogp_image`` being the project's
intended preview for the root page specifically has to be said explicitly; it is
never assumed just because it is the root page.

Whichever image ends up as the preview -- selected here, or ``ogp_image`` on a page
with none of its own -- gets ``og:image:width``/``height``/``type`` added from the
file itself, when it is one this build actually produced. The selected image's own
``alt`` text, if it has one, becomes ``og:image:alt``.

"""

from __future__ import annotations

from pathlib import Path
import posixpath
import struct
from typing import TYPE_CHECKING
from typing import Any
import urllib.parse

from docutils import nodes
from docutils.parsers.rst import Directive
from sphinx.util import logging

from . import _shared

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sphinx.application import Sphinx
    from sphinx.config import Config

logger = logging.getLogger(__name__)

CONFIG_VALUE = 'autoopengraph_image'

#: Document attribute holding the ``autoopengraph_thumbnail`` argument for the page
_THUMBNAIL_NUMBER = '_autoopengraph_thumbnail_number'


class OpenGraphThumbnailDirective(Directive):
    """The ``.. autoopengraph_thumbnail::`` directive.

    Selects which of the page's images is used as its Open Graph image. See this
    module's docstring. An argument of ``none`` opts the page out of selecting
    one of its own images entirely, falling back to the site-wide ``ogp_image``
    instead -- for a page whose own images exist but are not representative of
    it, the site's root page chief among them. (Not ``0``: this directive is
    otherwise one-based, with negative values counting from the end, so a ``0``
    meaning "none of the above" would read as an off-by-one rather than an
    intentional opt-out.)
    """

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False

    def run(self) -> list[nodes.Node]:
        """Record the page's thumbnail number and render nothing.

        Returns
        -------
        list[docutils.nodes.Node]
            Always empty; this directive has no visible output.

        """
        document = self.state_machine.document
        env = document.settings.env
        argument = self.arguments[0].strip()
        if argument.lower() == 'none':
            number = 0  # internal-only sentinel; never user-facing as a number
        else:
            try:
                number = int(argument)
            except ValueError as err:
                msg = f"'autoopengraph_thumbnail' expects an integer or 'none', got {argument!r}."
                raise self.error(msg) from err
            if number == 0:
                msg = (
                    "'autoopengraph_thumbnail' is one-based, so 0 is not a valid image "
                    "number. Use 1 for the first image, -1 for the last one, or 'none' "
                    'to opt the page out of selecting one of its own images entirely.'
                )
                raise self.error(msg)
        if _is_sphinx_gallery_document(env.app, env.docname):
            raise self.error(_gallery_thumbnail_error(argument))
        if _THUMBNAIL_NUMBER in document.attributes:
            # A warning rather than an error: Open Graph metadata is per-document, so a
            # page documenting several objects collides even when each of their own
            # sources is correct on its own generated page.
            logger.warning(
                'this page already selects image %d as its Open Graph image, and a page '
                'can only have one. Ignoring this selection of image %d.',
                document.attributes[_THUMBNAIL_NUMBER],
                number,
                location=(env.docname, self.lineno),
                type='autoopengraph',
                subtype='thumbnail',
            )
            return []
        document.attributes[_THUMBNAIL_NUMBER] = number
        return []


def _gallery_thumbnail_error(argument: str) -> str:
    """Return guidance for choosing a Sphinx-Gallery example's thumbnail."""
    if argument.lower() == 'none':
        return (
            "'autoopengraph_thumbnail' cannot be used in a Sphinx-Gallery example, "
            'because its Open Graph image always follows the gallery thumbnail, and '
            'Sphinx-Gallery has no equivalent to opting out. Use '
            "'sphinx_gallery_thumbnail_path' instead if none of the example's own "
            'figures represent it well.'
        )
    return (
        "'autoopengraph_thumbnail' cannot be used in a Sphinx-Gallery example, "
        'because its Open Graph image always follows the gallery thumbnail. '
        f"Use '# sphinx_gallery_thumbnail_number = {argument}' instead."
    )


def setup(app: Sphinx) -> None:
    """Wire up Open Graph images.

    Called by :mod:`sphinx_autoopengraph`; this module is not a Sphinx extension
    of its own.
    """
    app.add_directive('autoopengraph_thumbnail', OpenGraphThumbnailDirective)
    app.add_config_value(CONFIG_VALUE, default=True, rebuild='html', types=bool)
    # Must run before ``sphinxext.opengraph`` renders its tags at the default priority
    app.connect('html-page-context', _set_image, priority=400)


def _set_image(
    app: Sphinx,
    pagename: str,
    templatename: str,
    context: dict[str, Any],
    doctree: nodes.document | None,
) -> None:
    """Point the page's ``og:image`` at the image it selects.

    This runs at write time rather than while reading, because that is the first
    point at which an image's final ``_images`` filename is known: hash-based
    naming, parallel reads and Sphinx's own de-duplication all mean a page cannot
    predict where its own output ends up while it is still being parsed.
    """
    if doctree is None or not getattr(app.config, CONFIG_VALUE) or not _shared.is_enabled(app):
        return
    fields = _shared.page_fields(app, context)
    if fields is None or 'og:image' in fields:
        return

    if _is_sphinx_gallery_document(app, pagename):
        selected = _gallery_image(app, pagename, doctree)
    else:
        selected = _numbered_image(app, pagename, doctree)
    if selected is None:
        _add_fallback_image_metadata(app, fields)
        return

    url, alt = selected
    fields['og:image'] = url
    if alt:
        fields.setdefault('og:image:alt', alt)
    _add_image_metadata(app, url, fields)


def _numbered_image(
    app: Sphinx, docname: str, doctree: nodes.document
) -> tuple[str, str | None] | None:
    """Return the URL and alt text of the image a page selects by position."""
    number = doctree.get(_THUMBNAIL_NUMBER, 1)
    if number == 0:
        # Explicit opt-out: fall back to the site-wide ogp_image instead
        return None

    images = list(_image_nodes(doctree))
    if not images:
        return None

    index = number - 1 if number > 0 else number
    if not -len(images) <= index < len(images):
        # Not fatal: a build that deliberately skips rendering (e.g. PyVista's own
        # ``pyvista_plot_skip``) legitimately renders fewer images than the page
        # selects from, so fall back to the first image either way
        if not _skips_rendering(app.config):
            logger.warning(
                "'autoopengraph_thumbnail' selects image %d, but this page only "
                'has %d image(s). Using the first one.',
                number,
                len(images),
                location=docname,
                type='autoopengraph',
                subtype='thumbnail',
            )
        index = 0
    node = images[index]
    # Sphinx has already rewritten the URI to the image's path relative to this page
    return _absolute_url(app, docname, node['uri']), _image_alt(node)


def _image_alt(node: nodes.Element) -> str | None:
    """Return *node*'s ``alt`` text, if it has one worth using."""
    alt = node.get('alt')
    return alt.strip() if isinstance(alt, str) and alt.strip() else None


def _skips_rendering(config: Config) -> bool:
    """Return whether a build is known to deliberately render fewer images.

    Soft dependency on PyVista's ``pyvista.ext.plot_directive`` configuration: this
    module works without it, it just cannot explain a mismatch as well.
    """
    return bool(
        getattr(config, 'pyvista_plot_skip', False)
        or getattr(config, 'pyvista_plot_skip_optional', False)
    )


def _gallery_image(
    app: Sphinx, docname: str, doctree: nodes.document
) -> tuple[str, str | None] | None:
    """Return the URL and alt text of the image Sphinx-Gallery uses as a thumbnail.

    The full resolution image is preferred over the gallery's own thumbnail file,
    which is too small to make a good link preview, but it is always the same image
    the gallery shows.
    """
    source = Path(app.env.doc2path(docname))
    number, path = _gallery_thumbnail_selection(source.with_suffix('.py'))
    if path is None:
        prefix = f'sphx_glr_{source.stem}_'
        images = [
            image
            for image in _image_nodes(doctree)
            if posixpath.basename(image['uri']).startswith(prefix)
        ]
        index = number - 1 if number > 0 else number
        if -len(images) <= index < len(images):
            # Sphinx-Gallery copies its images into the output verbatim
            node = images[index]
            url = _absolute_url(app, docname, _output_image_path(app, node['uri']))
            return url, _image_alt(node)

    # ``sphinx_gallery_thumbnail_path`` and failed examples both leave a thumbnail with
    # no full resolution counterpart on the page, and no doctree node to take alt text from
    thumbnails = (source.parent / 'images' / 'thumb').glob(f'sphx_glr_{source.stem}_thumb.*')
    thumbnail = next(thumbnails, None)
    if thumbnail is None:
        return None
    url = _absolute_url(app, docname, _output_image_path(app, thumbnail.name))
    return url, None


def _gallery_thumbnail_selection(source: Path) -> tuple[int, str | None]:
    """Return the ``sphinx_gallery_thumbnail_{number,path}`` chosen by an example."""
    try:
        from sphinx_gallery.py_source_parser import extract_file_config
    except ImportError:  # pragma: no cover
        return 1, None
    try:
        file_conf = extract_file_config(source.read_text(encoding='utf-8'))
    except OSError:
        # Gallery index pages and ``sg_execution_times`` have no example source
        return 1, None
    # A number always wins over a path, matching ``sphinx_gallery.gen_rst.save_thumbnail``
    number = file_conf.get('thumbnail_number')
    if number is None:
        path = file_conf.get('thumbnail_path')
        return 1, None if path is None else str(path)
    return int(number), None


def _image_nodes(doctree: nodes.document) -> Iterator[nodes.Element]:
    """Yield every locally-rendered image-bearing node of a page, in document order.

    Sphinx-Gallery renders its images as ``imgsgnode`` rather than
    :class:`docutils.nodes.image`, so nodes are matched on carrying a ``uri``.
    An externally hosted image (any ``uri`` with a scheme, e.g. ``https://...``)
    is never a candidate: in practice these are almost always a badge, a shield,
    or a sponsor logo -- a CI status badge or a "launch on Binder" button, not
    something that represents the page -- and are excluded here rather than only
    from the default (unselected) case, since a directive-produced image is
    always local, so this never affects one.
    """
    for node in doctree.findall(nodes.Element):
        uri = node.get('uri')
        if uri and not urllib.parse.urlparse(uri).scheme:
            yield node


def _output_image_path(app: Sphinx, name: str) -> str:
    """Return the path of an output image, relative to the page being written."""
    return posixpath.join(app.builder.imgpath, posixpath.basename(name))


#: Extensions plot-generating extensions actually produce, mapped to their MIME type
_MIME_TYPES = {
    '.gif': 'image/gif',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}


def _add_fallback_image_metadata(app: Sphinx, fields: dict[str, str]) -> None:
    """Add ``og:image:width``/``height``/``type`` for the site-wide ``ogp_image``.

    A page with no image of its own never reaches ``_add_image_metadata``, since
    neither ``_numbered_image`` nor ``_gallery_image`` selects anything -- but
    ``sphinxext-opengraph`` still gives it a preview, via its own ``ogp_image``
    fallback, which deserves the same metadata.
    """
    if app.config.ogp_use_first_image:
        # sphinxext-opengraph uses the page's own first image instead of ogp_image
        # in this case, and nothing here has selected one to enrich
        return
    url = _resolve_ogp_image(app)
    if url is not None:
        _add_image_metadata(app, url, fields)


def _resolve_ogp_image(app: Sphinx) -> str | None:
    """Return the absolute URL ``sphinxext-opengraph`` uses for ``ogp_image``.

    Mirrors its own resolution: relative to ``ogp_site_url`` when ``ogp_image``
    has no scheme of its own, used as-is otherwise.
    """
    image = app.config.ogp_image
    if not image:
        return None
    if urllib.parse.urlparse(image).scheme:
        return image
    site_url = app.config.ogp_canonical_url or app.config.ogp_site_url
    return urllib.parse.urljoin(site_url, image)


def _add_image_metadata(app: Sphinx, url: str, fields: dict[str, str]) -> None:
    """Add ``og:image:width``/``height``/``type`` for a same-site, readable image.

    Consumers that lay out a preview before fetching the image -- LinkedIn among
    them -- use these to avoid guessing its aspect ratio. Silently does nothing for
    an image this build didn't render, such as one from an explicit ``:og:image:``
    override or an externally hosted ``.. image::``.
    """
    path = _local_image_path(app, url)
    if path is None:
        return
    mime = _MIME_TYPES.get(path.suffix.lower())
    if mime is not None:
        fields.setdefault('og:image:type', mime)
    dimensions = _read_dimensions(path)
    if dimensions is not None:
        width, height = dimensions
        fields.setdefault('og:image:width', str(width))
        fields.setdefault('og:image:height', str(height))


def _local_image_path(app: Sphinx, url: str) -> Path | None:
    """Return the on-disk file *url* was built from, or ``None`` if it isn't one.

    Prefers the original source file over the output copy under ``imagedir``
    (always ``_images``): Sphinx defers copying document-embedded images to a
    ``build-finished`` task (``copy_image_files``), so at ``html-page-context``
    time that copy may not exist yet, while the source has been on disk for the
    whole build. ``env.images`` maps each original source-relative path to the
    unique output basename Sphinx gave it, so *basename* is looked up there in
    reverse. Falls back to ``_static`` for a hand-curated ``ogp_image``, which
    ``html_static_path`` copies up front rather than deferring.

    ``app.builder.imgpath`` is *not* used for any of this -- it is relative to
    whatever page is currently being written, not to the output directory.
    """
    site_url = app.config.ogp_canonical_url or app.config.ogp_site_url
    if site_url and not url.startswith(site_url):
        return None
    basename = posixpath.basename(urllib.parse.urlparse(url).path)
    if not basename:
        return None

    for original, (_docnames, unique_name) in app.env.images.items():
        if unique_name == basename:
            source_path = Path(app.srcdir) / original
            if source_path.is_file():
                return source_path

    for directory in (app.builder.imagedir, '_static'):
        path = Path(app.outdir) / directory / basename
        if path.is_file():
            return path
    return None


def _read_dimensions(path: Path) -> tuple[int, int] | None:
    """Return an image's ``(width, height)`` in pixels.

    Only handles the formats plot-generating extensions actually produce (PNG,
    animated GIF); returns ``None`` for anything else rather than adding a
    dependency to parse it.
    """
    with path.open('rb') as file:
        header = file.read(26)
    if header[:8] == b'\x89PNG\r\n\x1a\n':
        return struct.unpack('>II', header[16:24])
    if header[:6] in (b'GIF87a', b'GIF89a'):
        return struct.unpack('<HH', header[6:10])
    return None


def _absolute_url(app: Sphinx, docname: str, path: str) -> str:
    """Return the public URL of *path*, which is relative to *docname*."""
    site_url = app.config.ogp_canonical_url or app.config.ogp_site_url
    page_url = urllib.parse.urljoin(site_url, app.builder.get_target_uri(docname))
    return urllib.parse.urljoin(page_url, path)


def _is_sphinx_gallery_document(app: Sphinx, docname: str) -> bool:
    """Return whether *docname* is a generated Sphinx-Gallery document."""
    gallery_conf = getattr(app.config, 'sphinx_gallery_conf', None)
    if not gallery_conf:
        return False

    gallery_dirs = gallery_conf.get('gallery_dirs', ())
    if isinstance(gallery_dirs, str):
        gallery_dirs = (gallery_dirs,)
    directories = [Path(directory).as_posix().strip('/') for directory in gallery_dirs]
    return any(
        docname == directory or docname.startswith(f'{directory}/') for directory in directories
    )
