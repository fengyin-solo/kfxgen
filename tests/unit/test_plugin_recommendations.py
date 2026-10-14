"""kfxgen recommends calibre keep the book's font sizes (#241).

Calibre's default font rescaling snaps sizes to its font-size key: pg3011's
0.9em verse came out 0.75, a quarter below its notes, where Kindle Previewer
writes 0.9. The output plugin recommends `disable_font_rescaling` at MED, so
a user's own Look & Feel setting still wins.
"""

import importlib
import sys
import types

import pytest


@pytest.fixture
def plugin_module(monkeypatch):
    conversion = types.ModuleType("calibre.customize.conversion")

    class OptionRecommendation:
        LOW, MED, HIGH = 1, 2, 3

        def __init__(self, **kw):
            self.__dict__.update(kw)

    class OutputFormatPlugin:
        pass

    conversion.OptionRecommendation = OptionRecommendation
    conversion.OutputFormatPlugin = OutputFormatPlugin
    for name in ("calibre", "calibre.customize"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "calibre.customize.conversion", conversion)
    monkeypatch.delitem(sys.modules, "plugin", raising=False)
    monkeypatch.syspath_prepend(".")
    return importlib.import_module("plugin")


@pytest.mark.unit
def test_recommends_keeping_the_books_font_sizes(plugin_module):
    rec = plugin_module.OptionRecommendation
    assert ("disable_font_rescaling", True, rec.MED) in (
        plugin_module.KFXGenOutputPlugin.recommendations
    )
