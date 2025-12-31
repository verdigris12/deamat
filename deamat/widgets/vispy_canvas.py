# VisPy ≥ 0.14 widget for deamat, with imgui_bundle ≥ 1.91.5
# Renders a VisPy SceneCanvas into an OpenGL texture and shows it via imgui.image().

from typing import Any, Dict, Tuple, Callable
import numpy as np
from OpenGL import GL as gl
from vispy import scene
from imgui_bundle import imgui
import glfw


def _make_imtexture_ref(tex_id: int) -> Any:
    """
    Wrap a GL texture name into an ImTextureRef expected by imgui.image().
    Newer imgui_bundle exposes ImTextureID(...) returning an ImTextureRef.
    """
    # Prefer ImTextureID (most common on recent imgui_bundle)
    if hasattr(imgui, "ImTextureID"):
        return imgui.ImTextureID(int(tex_id))
    # Fallback if the binding exposes ImTextureRef directly
    if hasattr(imgui, "ImTextureRef"):
        return imgui.ImTextureRef(int(tex_id))
    # If neither exists, we can’t satisfy imgui.image() contract
    raise RuntimeError("This imgui_bundle build requires an ImTextureRef/ImTextureID wrapper.")


def _create_texture(size: Tuple[int, int]) -> int:
    tex_id = int(gl.glGenTextures(1))
    w, h = size
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
    gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, w, h, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
    return tex_id


def _upload_rgba(tex_id: int, rgba: np.ndarray) -> None:
    # rgba is HxWx4 uint8; imgui expects origin at top-left, so we flip vertically
    h, w, _ = rgba.shape
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
    gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, rgba)


def vispy_canvas(gui: Any, state: Any, canvas_id: str, on_init: Callable[[scene.SceneCanvas, scene.widgets.ViewBox], None] | None = None) -> None:
    """
    Use inside an ImGui window; the canvas fills the entire content region.
    Exposes the SceneCanvas at gui.canvases[canvas_id].
    """
    registry = gui._vispy_canvases

    gui_ctx = gui.window  # GLFWwindow holding the main OpenGL context

    # Create on first use
    if canvas_id not in registry:
        canvas = scene.SceneCanvas(keys="interactive", size=(2, 2), show=False)
        view = canvas.central_widget.add_view()
        view.camera = scene.cameras.TurntableCamera()


        glfw.make_context_current(gui_ctx)
        tex_id = _create_texture((2, 2))
        tex_ref = _make_imtexture_ref(tex_id)

        registry[canvas_id] = {
            "canvas": canvas,
            "view": view,
            "tex_id": tex_id,
            "tex_ref": tex_ref,
            "size": (2, 2),
            "inited": False,
        }
        gui.canvases[canvas_id] = canvas
        # Run user init once the canvas exists
        if on_init is not None:
            on_init(canvas, view)

    entry = registry[canvas_id]
    canvas: scene.SceneCanvas = entry["canvas"]

    # Compute target size from available ImGui region
    avail = imgui.get_content_region_avail()
    size = (max(1, int(avail.x)), max(1, int(avail.y)))

    # Resize VisPy canvas and our GL texture if needed
    if size != entry["size"]:
        canvas.size = size
        glfw.make_context_current(gui_ctx)
        # Create new texture before deleting old one to avoid leak on failure
        new_tex = _create_texture(size)
        old_tex = entry["tex_id"]
        entry["tex_id"] = new_tex
        entry["tex_ref"] = _make_imtexture_ref(new_tex)
        entry["size"] = size
        gl.glDeleteTextures([old_tex])

    # Render with VisPy (this may switch to VisPy’s internal context)
    frame = canvas.render()  # returns HxWx4 uint8, origin bottom-left

    # Ensure we are back on the GUI context before touching GL
    glfw.make_context_current(gui_ctx)

    # Flip to top-left origin for ImGui
    frame_flipped = np.flipud(frame)
    _upload_rgba(entry["tex_id"], frame_flipped)

    # Draw as an ImGui image, filling the window
    # Note: imgui.image requires ImTextureRef and ImVec2
    imgui.image(
        entry["tex_ref"],
        imgui.ImVec2(float(size[0]), float(size[1])),
        imgui.ImVec2(0.0, 1.0),
        imgui.ImVec2(1.0, 0.0),
    )

