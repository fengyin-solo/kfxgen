"""Persistent plugin settings for kfxgen (Preferences -> Plugins -> Customize).

Qt-free so it is safe to import from the conversion worker (which reads the
setting) as well as the GUI config widget (which edits it). Stored at
``plugins/kfxgen.json`` in the Calibre config directory.
"""

from calibre.utils.config import JSONConfig

prefs = JSONConfig("plugins/kfxgen")

# Global default for the "Do not embed fonts" toggle. False -> embed the book's
# @font-face fonts (the default). The per-conversion CLI option
# `--kfxgen-disable-font-embedding` can also disable embedding; the two are OR'd.
prefs.defaults["disable_font_embedding"] = False

# Global default for "Write tables as one paragraph per row". False -> native
# Kindle tables (the default). The per-conversion CLI option
# `--kfxgen-disable-native-tables` can also disable them; the two are OR'd.
prefs.defaults["disable_native_tables"] = False

# Global default for "Open new books at the cover". False -> a book opens where
# it marks its text's start, as store books do (#579). The per-conversion CLI
# option `--kfxgen-open-at-cover` can also turn it on; the two are OR'd.
prefs.defaults["open_at_cover"] = False

# Global default for strict resource checking. False (the default) keeps the
# best-effort behaviour: a missing/damaged cover, picture, SVG or embedded
# font is skipped with a warning and conversion still writes a KFX. True makes
# any required resource the book's own HTML/CSS references but cannot use fail
# the conversion before a KFX is written. The per-conversion CLI option
# `--kfxgen-strict-resources` can also turn it on; the two are OR'd.
prefs.defaults["strict_resources"] = False
