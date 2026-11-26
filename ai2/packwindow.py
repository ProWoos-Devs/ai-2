"""Desktop entry for managing Knowledge Packs and creating them from local documents."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from . import about, doc, i18n, pack, packcreator, runtime
from .detect import detect
from .i18n import tr
from .models import RAM_HEADROOM_MIB


def button(label, action):
    widget = Gtk.Button.new_with_label(label)
    widget.connect("clicked", lambda *_: action())
    return widget


def scroll(widget, height):
    pane = Gtk.ScrolledWindow()
    pane.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    pane.set_min_content_height(height)
    pane.add(widget)
    return pane


class PackWindow(Gtk.Window):
    def __init__(self, create=False):
        super().__init__(title=tr("Knowledge Packs"))
        self.set_default_size(550, 420)
        self.set_border_width(14)
        self.connect("delete-event", self.closing)
        self.connect("destroy", lambda *_: Gtk.main_quit())
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(outer)
        self.page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.pack_start(scroll(self.page, 180), True, True, 0)
        self.status = Gtk.Label(xalign=0, selectable=True, wrap=True)
        self.status.set_max_width_chars(70)
        outer.pack_start(self.status, False, False, 0)
        self.bar = Gtk.ProgressBar()
        self.bar.set_no_show_all(True)
        outer.pack_start(self.bar, False, False, 0)
        self.cancel_button = button(tr("Cancel"), self.cancel)
        outer.pack_start(self.cancel_button, False, False, 0)
        self.cancel_button.set_no_show_all(True)
        self.busy = self.cancelled = self.close_after = self.pulsing = False
        self.process = None
        if create:
            self.editor()
        else:
            self.home()
        self.show_all()

    def clear(self, heading):
        for child in self.page.get_children():
            child.destroy()
        self.status.set_text("")
        self.set_title(heading)

    def add_to_page(self, widget, expand=False):
        self.page.pack_start(widget, expand, expand, 0)
        return widget

    def field(self, label, widget):
        caption = Gtk.Label(label=label, xalign=0)
        caption.set_mnemonic_widget(widget)
        widget.get_accessible().set_name(label)
        self.add_to_page(caption)
        return self.add_to_page(widget)

    def message(self, text, confirm=False):
        kind = Gtk.MessageType.QUESTION if confirm else Gtk.MessageType.WARNING
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=kind,
                                   buttons=Gtk.ButtonsType.OK_CANCEL if confirm else Gtk.ButtonsType.CLOSE)
        dialog.set_property("text", text[:4000])
        if confirm:
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
        answer = dialog.run()
        dialog.destroy()
        return answer == Gtk.ResponseType.OK

    def choose(self, title, action, patterns=(), multiple=False, name=None):
        label = tr("Save") if action == Gtk.FileChooserAction.SAVE else tr("Choose")
        dialog = Gtk.FileChooserDialog(title=title, transient_for=self, modal=True, action=action)
        dialog.add_buttons(tr("Cancel"), Gtk.ResponseType.CANCEL, label, Gtk.ResponseType.OK)
        dialog.set_select_multiple(multiple)
        if name:
            dialog.set_current_name(name)
            dialog.set_do_overwrite_confirmation(True)
        if action == Gtk.FileChooserAction.OPEN and not patterns:
            documents = Gtk.FileFilter()
            documents.set_name(tr("PDF and text documents"))
            for mime in ("application/pdf", "text/plain"):
                documents.add_mime_type(mime)
            for suffix in doc.TEXT_SUFFIXES:
                documents.add_pattern("*" + suffix)
            dialog.add_filter(documents)
            any_file = Gtk.FileFilter()
            any_file.set_name(tr("All files"))
            any_file.add_pattern("*")
            dialog.add_filter(any_file)
        if patterns:
            filt = Gtk.FileFilter()
            filt.set_name(title)
            for pattern in patterns:
                filt.add_pattern(pattern)
            dialog.add_filter(filt)
        result = dialog.get_filenames() if dialog.run() == Gtk.ResponseType.OK else []
        dialog.destroy()
        return result

    def cancel(self):
        self.cancelled = True
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def started(self, process):
        self.process = process
        if self.cancelled:
            process.terminate()

    def closing(self, *_):
        if self.busy:
            self.close_after = True
            if self.cancel_button.get_visible():
                self.cancel()
        return self.busy

    def job(self, status, work, finished, cancellable=False, bar=False):
        self.busy, self.cancelled, self.process = True, False, None
        self.page.set_sensitive(False)
        self.status.set_text(status)
        self.cancel_button.set_visible(cancellable)
        self.bar.set_visible(bar)
        self.pulsing = bar
        if bar:
            # nothing to measure yet (the model loads, the documents are read): show it is alive
            self.bar.set_fraction(0)
            GLib.timeout_add(150, self.pulse)

        def complete(result, error):
            self.process, self.busy = None, False
            self.page.set_sensitive(True)
            self.cancel_button.hide()
            self.pulsing = False
            self.bar.hide()
            if self.close_after:
                self.destroy()
            elif error:
                self.status.set_text(tr("Canceled.") if self.cancelled else tr("Please check the details and try again."))
                if not self.cancelled:
                    self.message(error)
            else:
                self.status.set_text("")
                finished(result)
            return False

        def worker():
            try:
                result = work()
            except Exception as exc:
                details = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
                GLib.idle_add(complete, None, details or str(exc))
            else:
                GLib.idle_add(complete, result, None)

        threading.Thread(target=worker, daemon=True).start()

    def progress(self, line):
        GLib.idle_add(self.status.set_text, line[:260])

    def pulse(self):
        if self.pulsing:
            self.bar.pulse()
        return self.pulsing

    def index_progress(self, info):
        """From the worker thread: how far the import is, on the bar and in words."""
        text = tr("Document {n} of {count}: {name}").format(n=info["document"], count=info["documents"],
                                                            name=info["name"])
        if info["minutes"] is not None:
            text += "\n" + tr("{done} of {total} parts, about {minutes} min left for this document").format(
                done=info["done"], total=info["total"], minutes=info["minutes"])

        def show():
            if self.busy:
                self.pulsing = False
                self.bar.set_fraction(info["fraction"])
                self.status.set_text(text)
            return False
        GLib.idle_add(show)

    def download_progress(self, line):
        """Only the search model's download is worth a raw line; the import has its own words."""
        if line.startswith("Downloading ") or re.match(r"\d+ MB\s", line):
            GLib.idle_add(self.status.set_text, line[:260])

    def home(self):
        self.clear(tr("Knowledge Packs"))
        self.add_to_page(button(tr("Create a Knowledge Pack"), self.editor))
        self.add_to_page(button(tr("Browse and update community Knowledge Packs"), self.browse))
        self.add_to_page(button(tr("Install a Knowledge Pack from a file"), self.install))
        collections = packcreator.private_collections()
        if collections:
            chooser = Gtk.ComboBoxText()
            for name, details in collections.items():
                chooser.append(name, f"{details['title']} ({name})")
            chooser.set_active(0)
            self.field(tr("My private collections"), chooser)
            self.add_to_page(button(tr("Open collection"), lambda: self.ready(chooser.get_active_id(),
                                                                      collections[chooser.get_active_id()])))
        self.page.show_all()

    def browse(self):
        cmd = about.terminal_window(tr("Knowledge Packs"), "100x38", ["ai-2", "knowledge", "browse"])
        if not about.open_window(cmd):
            self.message(tr("A terminal is needed to open the community catalog."))

    def install(self):
        files = self.choose(tr("Choose a Knowledge Pack"), Gtk.FileChooserAction.OPEN, ["*.ai2pack"])
        if not files:
            return
        try:
            manifest = pack.read_manifest(files[0])
            model = next(m for m in pack.embedding_models() if m["id"] == manifest["embedder"]["id"])
        except (pack.PackError, OSError, ValueError) as exc:
            self.message(str(exc))
            return
        prompt = tr("Install “{title}” on this computer?").format(title=manifest["title"])
        if pack.manifest_of(manifest["id"]):
            prompt += "\n" + tr("This will replace the installed copy.")
        if self.confirm_model(model, prompt, always=True):
            self.job(tr("Installing…"), lambda: packcreator.run_cli(["knowledge", "install", "--", files[0]],
                     report=self.progress), lambda _: self.status.set_text(tr("Knowledge Pack installed.")))

    def confirm_model(self, model, prompt, always=False):
        if runtime.find_model_file(model["file"]) is None:
            prompt += "\n" + tr("The search model needs a one-time download of {size} MB.").format(size=model["file_mb"])
            return self.message(prompt, confirm=True)
        return not always or self.message(prompt, confirm=True)

    def editor(self):
        self.clear(tr("Create a Knowledge Pack"))
        title = self.field(tr("Knowledge Pack title"), Gtk.Entry())
        languages = Gtk.ComboBoxText.new_with_entry()
        for code, label in {"en": "English", "es": "Español", "de": "Deutsch", "pl": "Polski"}.items():
            languages.append(code, label)
        if not languages.set_active_id(i18n._lang()):
            languages.set_active_id("en")
        self.field(tr("Document language (or enter a language code)"), languages)
        paths = Gtk.ListStore(str, str)
        files = Gtk.TreeView(model=paths, headers_visible=False)
        files.append_column(Gtk.TreeViewColumn(tr("Documents"), Gtk.CellRendererText(), text=1))
        files.get_accessible().set_name(tr("Documents"))
        self.add_to_page(scroll(files, 55))

        def add_paths(items):
            existing = {row[0] for row in paths}
            for path in items:
                if path and path not in existing:
                    paths.append([path, Path(path).name])
                    existing.add(path)

        def dropped(_widget, context, _x, _y, data, _info, time):
            local = [Gio.File.new_for_uri(uri).get_path() for uri in data.get_uris()]
            add_paths(local)
            Gtk.drag_finish(context, any(local), False, time)

        files.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        files.connect("drag-data-received", dropped)
        row = self.add_to_page(Gtk.Box(spacing=6))
        row.add(button(tr("Add documents…"), lambda: add_paths(self.choose(
            tr("PDF and text documents"), Gtk.FileChooserAction.OPEN, multiple=True))))

        def remove():
            model, selected = files.get_selection().get_selected()
            if selected:
                model.remove(selected)
        row.add(button(tr("Remove selected"), remove))
        notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        notes.get_accessible().set_name(tr("Paste notes (optional)"))
        self.add_to_page(Gtk.Label(label=tr("Paste notes (optional)"), xalign=0))
        self.add_to_page(scroll(notes, 64))

        def build():
            language = languages.get_active_id() or languages.get_child().get_text().strip()
            buf = notes.get_buffer()
            text = buf.get_text(*buf.get_bounds(), True)
            chosen = [row[0] for row in paths]
            name = title.get_text().strip()
            if not name or not (chosen or text.strip()):
                self.message(tr("Enter a title and add a document or some notes."))
                return
            if not packcreator.valid_language(language):
                self.message(tr("Choose a language for the documents."))
                return
            model = packcreator.model_for(language)
            if model["ram_peak_mb"] + RAM_HEADROOM_MIB > detect().ram_mib:
                self.message(tr("This computer has too little memory to build a Knowledge Pack in this language. "
                                "Create it on a computer with more memory and copy the Knowledge Pack file here."))
                return
            if self.confirm_model(model, tr("Create this private collection?")):
                self.job(tr("Creating your private collection…"), lambda: packcreator.create(
                    name, language, chosen, text, self.download_progress, self.started,
                    progress=self.index_progress), lambda result: self.ready(*result),
                    cancellable=True, bar=True)
        self.add_to_page(button(tr("Create"), build))
        self.add_to_page(button(tr("Back"), self.home))
        self.page.show_all()
        title.grab_focus()

    def ready(self, name, details):
        self.clear(details["title"])
        question = self.field(tr("Try a question about this collection"), Gtk.Entry())
        answers = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        answers.get_accessible().set_name(tr("Closest passages"))
        def search():
            query = question.get_text().strip()
            if query:
                self.job(tr("Searching…"), lambda: packcreator.try_question(name, query),
                         answers.get_buffer().set_text)
        question.connect("activate", lambda *_: search())
        self.add_to_page(button(tr("Search"), search))
        self.add_to_page(scroll(answers, 100), expand=True)

        def save():
            chosen = self.choose(tr("Save a Knowledge Pack file"), Gtk.FileChooserAction.SAVE, name=name + pack.SUFFIX)
            if not chosen:
                return
            path = Path(chosen[0])
            if not path.name.endswith(pack.SUFFIX):
                path = path.with_name(path.name + pack.SUFFIX)
                if path.exists() and not self.message(tr("Replace {path}?").format(path=path), confirm=True):
                    return
            self.job(tr("Saving…"), lambda: packcreator.save_pack(name, details, path),
                     lambda _: self.status.set_text(tr("Saved to {path}").format(path=path)))
        self.add_to_page(button(tr("Save a Knowledge Pack file"), save))
        self.add_to_page(button(tr("Prepare for community sharing"), lambda: self.community(name, details)))
        self.add_to_page(button(tr("Back"), self.home))
        self.page.show_all()
        question.grab_focus()

    def community(self, name, details):
        self.clear(tr("Prepare for community sharing"))
        contact = self.field(tr("Author or contact"), Gtk.Entry())
        credit = self.field(tr("Source and attribution"), Gtk.Entry())
        license_field = Gtk.ComboBoxText()
        for license_id in packcreator.LICENSES:
            license_field.append(license_id, license_id)
        self.field(tr("License for sharing these documents"), license_field)
        category = Gtk.ComboBoxText()
        for code, label in pack.load_categories()["categories"].items():
            category.append(code, f"{code}  {label}")
        self.field(tr("Catalog category"), category)
        children = self.add_to_page(Gtk.CheckButton(label=tr("Written for children")))
        age_box = self.add_to_page(Gtk.Box(orientation=Gtk.Orientation.VERTICAL))
        age_box.set_no_show_all(True)
        ages = {}
        for code, label in pack.load_categories()["ages"].items():
            ages[code] = Gtk.CheckButton(label=label)
            age_box.add(ages[code])
            ages[code].show()
        children.connect("toggled", lambda box: age_box.set_visible(box.get_active()))
        self.add_to_page(Gtk.LinkButton.new_with_label(pack.CATALOG_URL + "/blob/main/CONTRIBUTING.md",
                                               tr("Community submission guide")))

        def prepare():
            values = (contact.get_text(), license_field.get_active_id(), credit.get_text(), category.get_active_id())
            if not all(value and value.strip() for value in values):
                self.message(tr("Enter the author, source credits, license and category."))
                return
            selected_ages = [code for code, box in ages.items() if box.get_active()] if children.get_active() else []
            if children.get_active() and not selected_ages:
                self.message(tr("Choose at least one age range."))
                return
            chosen = self.choose(tr("Choose where to save the submission"), Gtk.FileChooserAction.SELECT_FOLDER)
            if chosen:
                self.job(tr("Checking the submission…"),
                         lambda: packcreator.prepare_community(name, details, chosen[0], *values, ages=selected_ages),
                         lambda folder: self.status.set_text(tr("Files ready in {path}. Use the guide to submit them.")
                                                            .format(path=folder)))
        self.add_to_page(button(tr("Prepare submission files"), prepare))
        self.add_to_page(button(tr("Back"), lambda: self.ready(name, details)))
        self.page.show_all()


def open_window(create=False):
    if not Gtk.init_check()[0]:
        return False
    window = PackWindow(create=create)
    window.present()
    Gtk.main()
    return True
