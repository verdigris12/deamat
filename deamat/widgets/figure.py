"""
Widgets for embedding matplotlib figures into an imgui interface.

The functions here are intended to be called from your UI update callback.  They
wrap up the bookkeeping needed to resize figures, redraw them on demand and
launch separate viewers for interactive inspection.
"""

import multiprocessing
import pickle
from typing import Any

import numpy as np
import wgpu
from imgui_bundle import portable_file_dialogs as pfd
from imgui_bundle import imgui

from deamat.mpl_view import MPLView

# Set spawn method once at module load to avoid issues on macOS with forking
try:
    multiprocessing.set_start_method('spawn')
except RuntimeError:
    pass  # Already set


def open_figure_in_pyplot(pickled_figure: bytes) -> None:
    """Spawn a new process to view a pickled figure using MPLView."""
    fig = pickle.loads(pickled_figure)
    view = MPLView(fig)
    view.run()


def _render_figure_to_rgba(figure: Any) -> np.ndarray:
    """Render a matplotlib figure to an RGBA numpy array.
    
    Parameters
    ----------
    figure : matplotlib.figure.Figure
        The figure to render.
        
    Returns
    -------
    np.ndarray
        RGBA image as uint8 array with shape (height, width, 4).
    """
    # Draw the figure to the canvas
    figure.canvas.draw()
    
    # Get the RGBA buffer
    w, h = figure.canvas.get_width_height()
    buf = np.frombuffer(figure.canvas.buffer_rgba(), dtype=np.uint8)
    buf = buf.reshape((h, w, 4))
    
    # Return a copy to ensure contiguous memory
    return np.ascontiguousarray(buf)


def _get_or_create_texture(
    gui: Any,
    fig_id: str,
    width: int,
    height: int,
) -> dict:
    """Get or create a texture entry for a matplotlib figure.
    
    Parameters
    ----------
    gui : GUI
        The deamat GUI instance.
    fig_id : str
        Unique identifier for this figure.
    width : int
        Texture width in pixels.
    height : int
        Texture height in pixels.
        
    Returns
    -------
    dict
        Texture entry with keys: texture, texture_view, tex_ref, size
    """
    # Initialize registry if needed
    if not hasattr(gui, '_mpl_textures'):
        gui._mpl_textures = {}
    
    registry = gui._mpl_textures
    device = gui.renderer.device
    
    # Check if we need to create or resize
    needs_create = fig_id not in registry
    if not needs_create:
        entry = registry[fig_id]
        if entry["size"] != (width, height):
            # Size changed, need to recreate
            gui.gui_renderer.backend.unregister_texture(entry["tex_ref"])
            entry["texture"].destroy()
            needs_create = True
    
    if needs_create:
        # Create wgpu texture for the figure
        texture = device.create_texture(
            label=f"mpl_figure_{fig_id}",
            size=(width, height, 1),
            format=wgpu.TextureFormat.rgba8unorm,
            usage=wgpu.TextureUsage.COPY_DST | wgpu.TextureUsage.TEXTURE_BINDING,
        )
        texture_view = texture.create_view()
        
        # Register with imgui backend
        tex_ref = gui.gui_renderer.backend.register_texture(texture_view)
        
        registry[fig_id] = {
            "texture": texture,
            "texture_view": texture_view,
            "tex_ref": tex_ref,
            "size": (width, height),
        }
    
    return registry[fig_id]


def _upload_rgba_to_texture(gui: Any, texture: Any, rgba: np.ndarray) -> None:
    """Upload RGBA data to a wgpu texture.
    
    Parameters
    ----------
    gui : GUI
        The deamat GUI instance.
    texture : wgpu.GPUTexture
        The target texture.
    rgba : np.ndarray
        RGBA image data with shape (height, width, 4).
    """
    height, width = rgba.shape[:2]
    gui.renderer.device.queue.write_texture(
        destination={"texture": texture, "origin": (0, 0, 0)},
        data=rgba,
        data_layout={"bytes_per_row": width * 4, "rows_per_image": height},
        size=(width, height, 1),
    )


def figure(
    gui: Any,
    state: Any,
    figname: str,
    width: int | None = None,
    height: int | None = None,
    autosize: bool = False,
) -> None:
    """Render a matplotlib figure inside an imgui window.

    Parameters
    ----------
    gui : GUI
        The deamat GUI instance.
    state : GUIState
        The current GUI state containing the registered figures.
    figname : str
        The key under which the figure was registered via ``add_figure``.
    width : int, optional
        Desired width in pixels.  If ``autosize`` is True this value is ignored.
    height : int, optional
        Desired height in pixels.  If ``autosize`` is True this value is ignored.
    autosize : bool, default False
        If True, the figure will be resized to fill the available content region.
    """
    fig_entry = state.figures[figname]
    
    if autosize:
        avail = imgui.get_content_region_avail()
        fig_entry['width'] = max(1, int(avail.x))
        fig_entry['height'] = max(1, int(avail.y))
    else:
        fig_entry['width'] = width if width is not None else fig_entry['width']
        fig_entry['height'] = height if height is not None else fig_entry['height']

    mpl_figure = fig_entry['figure']
    title = fig_entry['title']
    
    # Check if we need to refresh the texture
    needs_upload = fig_entry.get('texture_dirty', True)

    # Buttons row
    if imgui.button('Redraw ' + title):
        state.invalidate_figure(figname)

    imgui.same_line()

    if imgui.button('Open in viewer'):
        pickled_figure = pickle.dumps(mpl_figure)
        p = multiprocessing.Process(target=open_figure_in_pyplot, args=(pickled_figure,))
        p.start()

    imgui.same_line()

    if imgui.button('Save image'):
        fpath = pfd.save_file(title + '.png', state.figure_path).result()
        if len(fpath) > 0:
            state.figure_path = fpath
            mpl_figure.savefig(fpath)

    # Get display size
    display_width = int(fig_entry['width'])
    display_height = int(fig_entry['height'])
    
    if display_width < 1 or display_height < 1:
        return
    
    # Render figure to RGBA
    rgba = _render_figure_to_rgba(mpl_figure)
    img_height, img_width = rgba.shape[:2]
    
    # Get or create texture
    tex_entry = _get_or_create_texture(gui, figname, img_width, img_height)
    
    # Upload if needed (always upload for now since figure may have changed)
    # TODO: optimize by tracking figure content hash
    _upload_rgba_to_texture(gui, tex_entry["texture"], rgba)
    fig_entry['texture_dirty'] = False
    
    # Display the texture
    imgui.image(
        tex_entry["tex_ref"],
        imgui.ImVec2(float(display_width), float(display_height)),
    )


# Keep old name as alias for backward compatibility
im_plot_figure = figure
