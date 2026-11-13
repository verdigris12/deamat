"""OpenGL textures for CPU RGBA images."""

import numpy as np
from imgui_bundle import imgui
from OpenGL import GL


class ImageTexture:
    """A GUI-owned RGBA texture whose storage is reused until its size changes."""

    def __init__(self, gui, pixels):
        self._gui = gui
        self._texture = None
        self.ref = None
        self.size = None
        self.update(pixels)
        gui._images.add(self)

    def _delete(self, texture):
        def delete():
            if delete not in self._gui._deferred_image_deletions:
                return
            self._gui._deferred_image_deletions.remove(delete)
            self._gui.make_current()
            GL.glDeleteTextures([texture])

        self._gui._deferred_image_deletions.append(delete)
        if self._gui._frame_active:
            self._gui.post(delete)
        else:
            delete()

    def update(self, pixels):
        if self._texture == 0:
            raise RuntimeError("Cannot update a closed ImageTexture")
        rgba = np.ascontiguousarray(pixels, dtype=np.uint8)
        if rgba.ndim != 3 or rgba.shape[2] != 4:
            raise ValueError("pixels must have shape (height, width, 4)")
        height, width = rgba.shape[:2]
        self._gui.make_current()
        if self.size != (width, height):
            old = self._texture
            self._texture = int(GL.glGenTextures(1))
            self.ref = imgui.ImTextureRef(self._texture)
            self.size = (width, height)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0,
                            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, rgba)
            if old is not None:
                self._delete(old)
        else:
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, width, height,
                               GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, rgba)

    def close(self):
        if self._texture in (None, 0):
            return
        texture, self._texture = self._texture, 0
        self.ref = None
        self.size = None
        self._gui._images.discard(self)
        self._delete(texture)
