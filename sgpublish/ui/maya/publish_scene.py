from __future__ import absolute_import

import traceback
import time
import sys
import subprocess
import platform
import tempfile
import os
import re
import glob
import functools
import datetime
import itertools

from concurrent.futures import ThreadPoolExecutor

from PyQt4 import QtCore, QtGui
Qt = QtCore.Qt

from maya import cmds

from sgfs import SGFS

from .. import utils as ui_utils
from ... import utils
from ...io import maya as io_maya
from ..exporter.maya import publish as ui_publish

__also_reload__ = [
    '...io.maya',
    '...utils',
    '..exporter.maya.publish',
    '..utils',
    '..utils',
]


def basename(src_path=None):    
    basename = os.path.basename(src_path or cmds.file(q=True, sceneName=True))
    basename = os.path.splitext(basename)[0]
    basename = re.sub(r'_*[rv]\d+', '', basename)
    return basename
    
class SceneExporter(io_maya.Exporter):
    
    def __init__(self, **kwargs):
        
        kwargs.setdefault('filename_hint', basename())
        kwargs.setdefault('publish_type', 'maya_scene')
        
        super(SceneExporter, self).__init__(**kwargs)
    
    def before_export_publish(self, publisher, **kwargs):
        
        # Playblasts should be converted into frames.
        if publisher.frames_path and not publisher.movie_path:
            publisher.movie_path = publisher.frames_path
            publisher.frames_path = None
        
        super(SceneExporter, self).before_export_publish(publisher, **kwargs)
    
    def movie_path_from_frames(self, publisher, frames_path, **kwargs):
        
        # Put it in the dailies folder.
        # TODO: Do this with SGFS templates.
        project_root = publisher.sgfs.path_for_entity(publisher.link.project())
        path = os.path.join(
            project_root,
            'VFX_Dailies',
            datetime.datetime.now().strftime('%Y-%m-%d'),
            publisher.link.fetch('step.Step.code') or 'Unknown',
            publisher.name + '_v%04d.mov' % publisher.version,
        )
        
        # Make it unique.
        if os.path.exists(path):
            base, ext = os.path.splitext(path)
            for i in itertools.counter(1):
                path = '%s_%04d%s' % (base, i, ext)
                if not os.path.exists(path):
                    break
        
        # Assert the directory exists.
        dir_ = os.path.dirname(path)
        if not os.path.exists(dir_):
            os.makedirs(dir_)
        
        return path
    
    def movie_url_from_path(self, publisher, movie_path, **kwargs):
        return 'http://keyweb/' + os.path.abspath(movie_path).lstrip('/')
        
    def export_publish(self, publisher, **kwargs):
        
        # Save the file into the directory.
        src_path = cmds.file(q=True, sceneName=True)
        src_ext = os.path.splitext(src_path)[1]
        try:
            dst_path = os.path.join(publisher.directory, os.path.basename(src_path))
            maya_type = 'mayaBinary' if src_ext == '.mb' else 'mayaAscii'
            cmds.file(rename=dst_path)
            cmds.file(save=True, type=maya_type)
        finally:
            cmds.file(rename=src_path)
            
        # Set the primary path.
        publisher.path = dst_path


class Dialog(QtGui.QDialog):
    
    def __init__(self, exceptions=None):
        super(Dialog, self).__init__()
        self._setup_ui()
    
    def _setup_ui(self):

        self.setWindowTitle('Scene Publisher')
        self.setLayout(QtGui.QVBoxLayout())
        
        self._exporter = SceneExporter()
        
        self._publish_widget = ui_publish.Widget(self._exporter)
        self._publish_widget.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(self._publish_widget)
        
        self._publish_widget.beforeScreenshot.connect(self.hide)
        self._publish_widget.afterScreenshot.connect(self.show)
        
        button = QtGui.QPushButton('Publish')
        button.clicked.connect(self._on_submit)
        self.layout().addLayout(ui_utils.vbox(button))
        
        self._publish_widget.beforePlayblast.connect(self._before_playblast)
        self._publish_widget.afterPlayblast.connect(self._after_playblast)
        
        self._msgbox = None
    
    def _before_playblast(self):
        self.hide()
    
    def _after_playblast(self):
        self.show()
    
    def _on_submit(self, *args):
        
        # Make sure they want to proceed if there are changes to the file.
        if cmds.file(q=True, modified=True):
            res = QtGui.QMessageBox.warning(self,
                "Unsaved Changes",
                "Would you like to save your changes before publishing this file? The publish will have the changes either way.",
                QtGui.QMessageBox.Save | QtGui.QMessageBox.No | QtGui.QMessageBox.Cancel,
                QtGui.QMessageBox.Save
            )
            if res & QtGui.QMessageBox.Save:
                cmds.file(save=True)
            if res & QtGui.QMessageBox.Cancel:
                return
        
        # DO IT
        publisher = self._publish_widget.export()
        
        # Version-up the file.
        src_path = cmds.file(q=True, sceneName=True)
        new_path = utils.get_next_revision_path(os.path.dirname(src_path), basename(src_path), os.path.splitext(src_path)[1], publisher.version + 1)
        cmds.file(rename=new_path)
        # cmds.file(save=True, type=maya_type)
        
        ui_utils.announce_publish_success(
            publisher,
            message="Version {publisher.version} of \"{publisher.name}\" has been published\n"
                "and your scene has been versioned up."
        )
        
        self.close()



def __before_reload__():
    # We have to manually clean this, since we aren't totally sure it will
    # always fall out of scope.
    global dialog
    if dialog:
        dialog.close()
        dialog.destroy()
        dialog = None


dialog = None


def run():
    global dialog
    if dialog:
        dialog.close()
    
    # Make sure the file was saved once.
    # TODO: Remove this restriction eventually.
    filename = cmds.file(q=True, sceneName=True)
    if not filename:
        QtGui.QMessageBox.warning(None, 'Unsaved Scene', 'The scene must be saved once before it can be published.')
        return
    
    workspace = cmds.workspace(q=True, rootDirectory=True)
    if not filename.startswith(workspace):
        res = QtGui.QMessageBox.warning(None, 'Mismatched Workspace', 'This scene is not from the current workspace. Continue anyways?',
            QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
            QtGui.QMessageBox.No
        )
        if res & QtGui.QMessageBox.No:
            return
    
    dialog = Dialog()
    dialog.show()
        