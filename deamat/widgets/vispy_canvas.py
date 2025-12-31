# VisPy widget for deamat
# Renders a VisPy SceneCanvas into an OpenGL texture and shows it via imgui.image().
# Includes event forwarding for interactive camera controls.

from typing import Any, Callable
import numpy as np
from OpenGL import GL as gl
from vispy import scene, app
from vispy.util import keys as vispy_keys
from imgui_bundle import imgui
import glfw

# Force VisPy to use GLFW backend
app.use_app('glfw')


def _make_imtexture_ref(tex_id: int) -> Any:
    """
    Wrap a GL texture name into an ImTextureRef expected by imgui.image().
    Newer imgui_bundle exposes ImTextureID(...) returning an ImTextureRef.
    """
    if hasattr(imgui, "ImTextureID"):
        return imgui.ImTextureID(int(tex_id))
    if hasattr(imgui, "ImTextureRef"):
        return imgui.ImTextureRef(int(tex_id))
    raise RuntimeError("This imgui_bundle build requires an ImTextureRef/ImTextureID wrapper.")


def _create_texture(size: tuple[int, int]) -> int:
    """Create an OpenGL texture in the current context."""
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
    """Upload RGBA pixel data to a texture."""
    h, w, _ = rgba.shape
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
    gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, rgba)


def _forward_events(canvas: scene.SceneCanvas, size: tuple[int, int]) -> None:
    """
    Forward ImGui mouse/keyboard events to VisPy canvas when widget is hovered.
    
    This enables interactive camera controls (TurntableCamera, etc.) to work
    with mouse drag, scroll, etc.
    """
    if not imgui.is_item_hovered():
        return
    
    io = imgui.get_io()
    
    # Calculate mouse position relative to widget (top-left origin)
    item_min = imgui.get_item_rect_min()
    mouse_x = io.mouse_pos.x - item_min.x
    mouse_y = io.mouse_pos.y - item_min.y
    
    # VisPy uses bottom-left origin, so flip Y
    mouse_y_vispy = size[1] - mouse_y
    pos = (mouse_x, mouse_y_vispy)
    
    # Build modifier list
    modifiers = []
    if io.key_shift:
        modifiers.append(vispy_keys.SHIFT)
    if io.key_ctrl:
        modifiers.append(vispy_keys.CONTROL)
    if io.key_alt:
        modifiers.append(vispy_keys.ALT)
    modifiers = tuple(modifiers)
    
    # Button mapping: ImGui (0=left, 1=right, 2=middle) -> VisPy (1=left, 2=right, 3=middle)
    button_map = {0: 1, 1: 2, 2: 3}
    
    # Track which buttons are currently pressed for move events
    buttons_pressed = []
    for imgui_btn, vispy_btn in button_map.items():
        if io.mouse_down[imgui_btn]:
            buttons_pressed.append(vispy_btn)
    
    # Mouse press events
    for imgui_btn, vispy_btn in button_map.items():
        if imgui.is_mouse_clicked(imgui_btn):
            canvas.events.mouse_press(  # type: ignore[attr-defined]
                pos=pos,
                button=vispy_btn,
                buttons=buttons_pressed,
                modifiers=modifiers,
            )
    
    # Mouse release events
    for imgui_btn, vispy_btn in button_map.items():
        if imgui.is_mouse_released(imgui_btn):
            canvas.events.mouse_release(  # type: ignore[attr-defined]
                pos=pos,
                button=vispy_btn,
                buttons=buttons_pressed,
                modifiers=modifiers,
            )
    
    # Mouse move events (always emit when hovered, VisPy cameras need this for drag)
    canvas.events.mouse_move(  # type: ignore[attr-defined]
        pos=pos,
        button=buttons_pressed[0] if buttons_pressed else None,
        buttons=buttons_pressed,
        modifiers=modifiers,
    )
    
    # Mouse wheel events
    wheel_y = io.mouse_wheel
    wheel_x = io.mouse_wheel_h
    if wheel_x != 0 or wheel_y != 0:
        canvas.events.mouse_wheel(  # type: ignore[attr-defined]
            pos=pos,
            delta=(wheel_x, wheel_y),
            modifiers=modifiers,
        )


def vispy_canvas(
    gui: Any,
    state: Any,
    canvas_id: str,
    on_init: Callable[[scene.SceneCanvas, scene.widgets.ViewBox], None] | None = None,
) -> None:
    """
    Embed a VisPy SceneCanvas as an ImGui widget.
    
    Use inside an ImGui window; the canvas fills the entire content region.
    The SceneCanvas is accessible at gui.canvases[canvas_id].
    
    Mouse and keyboard events are forwarded to VisPy when the widget is hovered,
    enabling interactive camera controls.

    Parameters
    ----------
    gui : GUI
        The deamat GUI instance.
    state : GUIState
        The application state.
    canvas_id : str
        Unique identifier for this canvas.
    on_init : callable, optional
        Callback invoked once when the canvas is created, receiving
        (canvas, view) as arguments. Use this to add visuals to the scene.
    """
    registry = gui._vispy_canvases
    gui_ctx = gui.window

    # Compute target size from available ImGui region
    avail = imgui.get_content_region_avail()
    display_size = (max(1, int(avail.x)), max(1, int(avail.y)))

    # Create on first use
    if canvas_id not in registry:
        canvas = scene.SceneCanvas(keys="interactive", size=display_size, show=False)
        view = canvas.central_widget.add_view()
        view.camera = scene.cameras.TurntableCamera()

        # Run user init callback
        if on_init is not None:
            on_init(canvas, view)

        # Create texture in GUI context
        glfw.make_context_current(gui_ctx)
        tex_id = _create_texture(display_size)
        tex_ref = _make_imtexture_ref(tex_id)

        registry[canvas_id] = {
            "canvas": canvas,
            "view": view,
            "tex_id": tex_id,
            "tex_ref": tex_ref,
            "display_size": display_size,
        }
        gui.canvases[canvas_id] = canvas

    entry = registry[canvas_id]
    canvas: scene.SceneCanvas = entry["canvas"]

    # Resize VisPy canvas and our GL texture if needed
    if display_size != entry["display_size"]:
        canvas.size = display_size
        glfw.make_context_current(gui_ctx)
        # Create new texture before deleting old one
        new_tex = _create_texture(display_size)
        old_tex = entry["tex_id"]
        entry["tex_id"] = new_tex
        entry["tex_ref"] = _make_imtexture_ref(new_tex)
        entry["display_size"] = display_size
        gl.glDeleteTextures([old_tex])

    # Render with VisPy (switches to VisPy's internal context)
    frame = canvas.render()  # returns HxWx4 uint8, origin bottom-left

    # Ensure we are back on the GUI context before touching GL
    glfw.make_context_current(gui_ctx)

    # Flip to top-left origin for ImGui
    frame_flipped = np.flipud(frame)

    _upload_rgba(entry["tex_id"], frame_flipped)

    # Draw as an ImGui image
    imgui.image(
        entry["tex_ref"],
        imgui.ImVec2(float(display_size[0]), float(display_size[1])),
    )

    # Forward mouse/keyboard events to VisPy for interactivity
    _forward_events(canvas, display_size)
