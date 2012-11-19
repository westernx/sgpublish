import functools
import os
import re
import tempfile
import traceback

from PyQt4 import QtCore, QtGui
Qt = QtCore.Qt

from sgfs import SGFS

from ..utils import ComboBox, hbox, vbox
from .. import utils

__also_reload__ = ['..utils', '...io.base']


class Widget(QtGui.QWidget):
    
    # Windows should hide on these.
    beforeScreenshot = QtCore.pyqtSignal()
    afterScreenshot = QtCore.pyqtSignal()
    
    # Need a signal to communicate across threads.
    loaded_publishes = QtCore.pyqtSignal(object, object)
    
    def __init__(self, exporter):
        super(Widget, self).__init__()
        
        self._exporter = exporter
        
        basename = os.path.basename(exporter.filename_hint)
        basename = os.path.splitext(basename)[0]
        self._basename = re.sub(r'_*[rv]\d+', '', basename)
        
        self._setup_ui()
    
    def _setup_ui(self):
        
        self.setLayout(QtGui.QVBoxLayout())
        
        self._task_combo = ComboBox()
        self._task_combo.addItem('Loading...', {'loading': True})
        self._task_combo.currentIndexChanged.connect(self._task_changed)
        
        self._name_combo = ComboBox()
        self._name_combo.addItem('Loading...', {'loading': True})
        self._name_combo.addItem('Create new stream...', {'new': True})
        self._name_combo.currentIndexChanged.connect(self._name_changed)
        
        self._name_field = QtGui.QLineEdit(self._basename)
        self._name_field.setEnabled(False)
        
        self._version_spinbox = QtGui.QSpinBox()
        self._version_spinbox.setMinimum(1)
        self._version_spinbox.setMaximum(9999)
        self._version_spinbox.valueChanged.connect(self._on_version_changed)
        self._version_warning_issued = False
        
        self.layout().addLayout(hbox(
            vbox("Task", self._task_combo),
            vbox("Publish Stream", self._name_combo),
        ))
        
        self.layout().addLayout(hbox(
            vbox("Name", self._name_field),
            vbox("Version", self._version_spinbox),
        ))
        
        # Get publish data in the background.
        self.loaded_publishes.connect(self._populate_existing_data)
        self._thread = QtCore.QThread()
        self._thread.run = self._fetch_existing_data
        self._thread.start()
        
        self._description = QtGui.QTextEdit('')
        self._description.setMaximumHeight(100)
        
        self._screenshot_path = None
        self._screenshot = QtGui.QLabel()
        self._screenshot.setFrameShadow(QtGui.QFrame.Sunken)
        self._screenshot.setFrameShape(QtGui.QFrame.Panel)
        self._screenshot.setToolTip("Click to specify part of screen.")
        self._screenshot.mouseReleaseEvent = self.take_partial_screenshot
        
        self.layout().addLayout(hbox(
            vbox("Describe Your Changes", self._description),
            vbox("Screenshot", self._screenshot),
        ))
        
        self.take_full_screenshot()
    
    def _fetch_existing_data(self):
        try:
            sgfs = SGFS()
            tasks = sgfs.entities_from_path(self._exporter.workspace)
            if not tasks:
                raise ValueError('No entities in workspace %r', self._exporter.workspace)
            if any(x['type'] != 'Task' for x in tasks):
                raise ValueError('Non-Task entity in workspace %r', self._exporter.workspace)
            publishes = sgfs.session.find(
                'PublishEvent',
                [
                    ('sg_link.Task.id', 'in') + tuple(x['id'] for x in tasks),
                    ('sg_type', 'is', self._exporter.publish_type)
                ], [
                    'code',
                    'sg_version'
                ]
            )

        except:
            self._task_combo.clear()
            self._task_combo.addItem('Loading Error!', {})
            raise
        
        else:
            self.loaded_publishes.emit(tasks, publishes)
        
    def _populate_existing_data(self, tasks, publishes):
        
        history = self._exporter.get_previous_publish_ids()
        
        select = None
        
        for t_i, task in enumerate(tasks):
            name_to_version = {}
            for publish in publishes:
                if publish['sg_link'] is not task:
                    continue
                name = publish['code']
                name_to_version[name] = max(name_to_version.get(name, 0), publish['sg_version'])
                
                if publish['id'] in history:
                    select = t_i, name
            
            self._task_combo.addItem('%s - %s' % task.fetch(('step.Step.short_name', 'content')), {
                'task': task,
                'publishes': name_to_version,
            })
        
        if 'loading' in self._task_combo.itemData(0):
            if self._task_combo.currentIndex() == 0:
                self._task_combo.setCurrentIndex(1)
            self._task_combo.removeItem(0)
        
        if select:
            self._task_combo.setCurrentIndex(select[0])
            for i in xrange(self._name_combo.count()):
                data = self._name_combo.itemData(i)
                if data and data.get('name') == select[1]:
                    self._name_combo.setCurrentIndex(i)
                    break
    
    def _task_changed(self, index):
        data = self._name_combo.currentData()
        if not data:
            return
        was_new = 'new' in data
        self._name_combo.clear()
        data = self._task_combo.currentData() or {}
        
        for name, version in sorted(data.get('publishes', {}).iteritems()):
            self._name_combo.addItem('%s (v%04d)' % (name, version), {'name': name, 'version': version})
        self._name_combo.addItem('Create New Stream...', {'new': True})
        if was_new:
            self._name_combo.setCurrentIndex(self._name_combo.count() - 1)
        else:
            self._name_combo.setCurrentIndex(0)
        
    def _name_changed(self, index):
        data = self._name_combo.itemData(index)
        if not data:
            return
        self._name_field.setEnabled('new' in data)
        self._name_field.setText(data.get('name', self._basename))
        self._version_spinbox.setMinimum(data.get('version', 0) + 1)
        self._version_spinbox.setValue(data.get('version', 0) + 1)
    
    def _on_version_changed(self, new_value):
        if new_value > self._version_spinbox.minimum() and not self._version_warning_issued:
            res = QtGui.QMessageBox.warning(None,
                "Manual Versions?",
                "Are you sure you want to change the version?\n"
                "The next one has already been selected for you...",
                QtGui.QMessageBox.Ok | QtGui.QMessageBox.Cancel,
                QtGui.QMessageBox.Cancel
            )
            if res & QtGui.QMessageBox.Cancel:
                self._version_spinbox.setValue(self._version_spinbox.minimum())
                return
            self._version_warning_issued = True
        
    def take_full_screenshot(self):
        
        # TODO: push this off into the maya-specific exporter
        
        try:
            from maya import cmds
        except ImportError:
            pass
        
        # Playblast the first screenshot.
        path = tempfile.NamedTemporaryFile(suffix=".jpg", prefix="publish", delete=False).name
        image_format = cmds.getAttr('defaultRenderGlobals.imageFormat')
        cmds.setAttr('defaultRenderGlobals.imageFormat', 8)
        try:
            frame = cmds.currentTime(q=True)
            cmds.playblast(
                frame=[frame],
                format='image',
                completeFilename=path,
                viewer=False,
                p=100,
                framePadding=4,
            )
        finally:
            cmds.setAttr('defaultRenderGlobals.imageFormat', image_format)
        self.setScreenshot(path)
    
    def take_partial_screenshot(self, *args):
        path = tempfile.NamedTemporaryFile(suffix=".png", prefix="screenshot", delete=False).name

        self.beforeScreenshot.emit()
        
        if platform.system() == "Darwin":
            # use built-in screenshot command on the mac
            proc = subprocess.Popen(['screencapture', '-mis', path])
        else:
            proc = subprocess.Popen(['import', path])
        proc.wait()
        
        self.afterScreenshot.emit()
        
        if os.stat(path).st_size:
            self.setScreenshot(path)
    
    def setScreenshot(self, path):
        self._screenshot_path = path
        pixmap = QtGui.QPixmap(path).scaled(200, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._screenshot.setPixmap(pixmap)
        self._screenshot.setFixedSize(pixmap.size())
    
    def name(self):
        data = self._name_combo.currentData()
        return data.get('name', str(self._name_field.text()))
        
    def description(self):
        return str(self._description.toPlainText())
    
    def version(self):
        return self._version_spinbox.value()
    
    def screenshot_path(self):
        return self._screenshot_path
    
    def export(self, **kwargs):
        
        data = self._task_combo.currentData()
        task = data.get('task')
        if not task:
            sgfs = SGFS()
            tasks = sgfs.entities_from_path(self._exporter.workspace, 'Task')
            if not tasks:
                raise ValueError('Could not find SGFS tagged entities')
            task = tasks[0]
        
        return self._exporter.publish(
            task, self.name(), self.description(), self.version(), self.screenshot_path(),
            **kwargs
        )

