"""Gallery Example With A Thumbnail Path
=======================================

Draw a line, but preview it with a hand-picked thumbnail image instead of
either rendered figure.
"""

# sphinx_gallery_thumbnail_path = '_static/custom_thumb.png'

from __future__ import annotations

import matplotlib.pyplot as plt

# %%
# Neither figure below is used as the thumbnail.
plt.figure()
plt.plot([1, 2, 3])
plt.show()

# %%
# This one is not either.
plt.figure()
plt.plot([3, 2, 1])
plt.show()
