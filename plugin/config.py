"""GUI config widget for kfxgen (Preferences -> Plugins -> Customize).

Imported only in the GUI (from `config_widget()`), so Qt is imported here rather
than in the conversion worker. The settings are the global font-embedding and
native-table defaults; the per-conversion CLI flags can still disable them.
"""

import os

from qt.core import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from calibre_plugins.kfxgen.prefs import prefs


class ConfigWidget(QWidget):
    def __init__(self):
        QWidget.__init__(self)
        layout = QVBoxLayout(self)

        self.disable_fonts = QCheckBox("Do not embed fonts", self)
        self.disable_fonts.setToolTip(
            "Embedding is on by default, so a book's own @font-face fonts render "
            "on-device. Check this to skip embedding and use the font "
            "installed/selected on the Kindle instead. The per-conversion "
            "--kfxgen-disable-font-embedding option can also disable it."
        )
        self.disable_fonts.setChecked(bool(prefs["disable_font_embedding"]))
        layout.addWidget(self.disable_fonts)

        self.disable_tables = QCheckBox("Write tables as one paragraph per row", self)
        self.disable_tables.setToolTip(
            "Use this if a book's tables display badly on your Kindle. By default "
            "kfxgen writes native Kindle tables. The per-conversion "
            "--kfxgen-disable-native-tables option can also disable them."
        )
        self.disable_tables.setChecked(bool(prefs["disable_native_tables"]))
        layout.addWidget(self.disable_tables)

        self.open_at_cover = QCheckBox("Open new books at the cover", self)
        self.open_at_cover.setToolTip(
            "By default a new book opens where it marks the start of its text, "
            "usually the first chapter, as store books do. Check this to open "
            "it at the cover instead. The per-conversion --kfxgen-open-at-cover "
            "option can also turn it on."
        )
        self.open_at_cover.setChecked(bool(prefs["open_at_cover"]))
        layout.addWidget(self.open_at_cover)

        report_label = QLabel("Conversion report (JSON), optional:", self)
        report_label.setToolTip(
            "After each successful KFX conversion, write a JSON report to this "
            "file: chapter and character counts, TOC/landmark/page-list counts, "
            "cover and image results, embedded fonts, removed or unresolvable "
            "resources, media coverage and structured warnings. Leave blank to "
            "write none. The file is replaced atomically on every conversion; "
            "its parent folder must already exist. The per-conversion "
            "--kfxgen-report-path option overrides this."
        )
        layout.addWidget(report_label)

        report_row = QHBoxLayout()
        self.report_path = QLineEdit(self)
        self.report_path.setPlaceholderText("No report")
        self.report_path.setText(str(prefs["report_path"] or ""))
        self.report_path.setToolTip(report_label.toolTip())
        report_row.addWidget(self.report_path)
        self.report_browse = QPushButton("Browse…", self)
        self.report_browse.clicked.connect(self._choose_report_path)
        report_row.addWidget(self.report_browse)
        layout.addLayout(report_row)

        layout.addStretch(1)

    def _choose_report_path(self):
        start = self.report_path.text().strip() or os.path.expanduser("~")
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Choose the kfxgen conversion report file",
            start,
            "JSON reports (*.json);;All files (*)",
        )
        if path:
            self.report_path.setText(path)

    def save_settings(self):
        prefs["disable_font_embedding"] = self.disable_fonts.isChecked()
        prefs["disable_native_tables"] = self.disable_tables.isChecked()
        prefs["open_at_cover"] = self.open_at_cover.isChecked()
        prefs["report_path"] = self.report_path.text().strip()
