import os

import uifutures

from ..publisher import Publisher
from . import ffmpeg

__also_reload__ = [
    '..publisher',
    '.ffmpeg',
]


class Exporter(object):
    
    def __init__(self, workspace=None, filename_hint=None, publish_type=None):
        self._workspace = workspace
        self._filename_hint = filename_hint
        self._publish_type = publish_type

    @property
    def publish_type(self):
        """The type of publish to create for this exporter."""
        return self._publish_type
    
    @property
    def filename_hint(self):
        """A filename for extracting info from, or using as a base to construct
        the final path if not supplied."""
        return self._filename_hint
    
    @property
    def workspace(self):
        """The working directory, usually corresponds to an SGFS tag."""
        return self._workspace or os.getcwd()
    
    def get_previous_publish_ids(self):
        """A set of previous publish IDs that current context was involved in.
        
        These publishes are used by the GUI to determine which publish stream
        to automatically select.
        
        Currently only supported in the Maya classes; please extend for your
        applications.
        
        """
        return set()
    
    def record_publish_id(self, id_):
        """Save the new publish ID in the current scene/script/context.
        
        These publishes will later be returned by :meth:`get_previous_publish_ids`.
        
        Currently only supported in the Maya classes; please extend for your
        applications.
        
        """
        pass
    
    def publish(self, link, name, export_kwargs=None, **publisher_kwargs):
        """Trigger a publish.
        
        This method only deals with setting up the publisher, and uses
        :meth:`export_publish` to do the work.
        
        :param export_kwargs: Passed to :meth:`export_publish`.
        :returns: The publisher used.
        
        """
        publish_type = self.publish_type
        if not publish_type:
            raise ValueError('cannot publish without type')
        
        with Publisher(link, publish_type, name, **publisher_kwargs) as publisher:
            
            # Record the ID before the export so that it is included.
            self.record_publish_id(publisher.id)
            
            # This is a hook that everyone should allow to go up the full chain.
            self.before_export_publish(publisher, **export_kwargs)
            
            # Ask children if there is a set of frames that we should convert
            # into a quicktime and save on the publisher.
            frames_path = self.frames_for_movie(publisher, **export_kwargs)
            if frames_path:
                movie_path = self.make_movie(publisher, frames_path, **export_kwargs)
                if movie_path:
                    publisher.movie_path = movie_path
            
            # Ask children for the url for the given movie.
            if publisher.movie_path and not publisher.movie_url:
                publisher.movie_url = self.movie_url_from_path(publisher, publisher.movie_path, **export_kwargs)
            
            # Completely overridable by children (without calling super).
            self.export_publish(publisher, **export_kwargs)
            
            return publisher
    
    def before_export_publish(self, publisher, **kwargs):
        pass
    
    def _path_is_image(self, path):
        if os.path.splitext(path)[1][1:].lower() in (
            'jpg', 'jpeg', 'tif', 'tiff', 'exr',
        ):
            return path
    
    def frames_for_movie(self, publisher, **kwargs):
        if self._path_is_image(publisher.movie_path):
            return publisher.movie_path
    
    def movie_path_from_frames(self, publisher, frames_path, **kwargs):
        return os.path.join(os.path.dirname(frames_path), 'movie.mov')
    
    def movie_url_from_path(self, publisher, movie_path, **kwargs):
        return None
    
    def make_movie(self, publisher, frames_path, **kwargs):
        movie_path = self.movie_path_from_frames(publisher, frames_path, **kwargs)
        with uifutures.Executor() as executor:
            executor.submit_ext(
                ffmpeg.quicktime_from_glob,
                args=(movie_path, frames_path),
                name='Create QuickTime for %s v%04d' % (publisher.name, publisher.version),
            )
        return movie_path
    
    def promotion_fields(self, publisher, **kwargs):
        return {}
    
    def export_publish(self, publisher, **kwargs):
        """Perform an export within the context of a publish.
        
        By default this simply calls :meth:`export` with the publish directory
        and no path.
        
        :param kwargs: Passed to :meth:`export_publish`.
        
        """
        return self.export(publisher.directory, None, **kwargs)
    
    def export(self, directory, path, **kwargs):
        """Do the work of exporting. Must be implemented in subclasses.
        
        :param str directory: The directory to publish in. If ``path`` is present
            then this may be assumed equal to ``os.path.dirname(path)``.
        :param path: The path to export to. Will always be ``None`` when
            publishing, and future use of ``None`` is reserved for complex
            exports, such as geocaches.
        :type path: str or None
        :param kwargs: Extra keyword arguments passed from the exporting widgets.
        
        """
        raise NotImplementedError()


class Importer(object):
    
    @property
    def existing_publish(self):
    
        path = self.existing_path
        if path is None:
            return
            
        entities = self.sgfs.entities_for_path(path, 'PublishEvent')
        if len(entities) > 1:
            raise RuntimeError('multiple publishes tagged in %r' % path)
        return entities[0] if entities else None
    
    @property
    def existing_path(self):
        # For the UI to repopulate.
        return None
        
    def import_publish(self, publish):
        # This gets the entity, not a Publisher.
        # Call `self.import(publish['sg_path'])`.
        pass
    
    def import_(self, path):
        raise NotImplementedError()