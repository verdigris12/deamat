# pygfx widget for deamat
# Renders a pygfx Scene into an OpenGL texture and shows it via imgui.image().
# Includes event forwarding for interactive OrbitController.
#
# IMPORTANT: pygfx requires a GPU with Vulkan support OR a system where wgpu's
# OpenGL/EGL backend doesn't conflict with GLFW's OpenGL context. On some systems
# (e.g., Intel integrated GPUs with only Mesa OpenGL), wgpu's EGL context conflicts
# with GLFW, causing a crash. In such cases, use vispy_canvas instead.

from typing import Any, Callable
import logging
import numpy as np
from OpenGL import GL as gl
import pygfx as gfx
from pygfx.renderers.wgpu.engine.shared import enable_wgpu_features
from rendercanvas.offscreen import RenderCanvas
from imgui_bundle import imgui
import glfw

logger = logging.getLogger(__name__)

# Disable float32-filterable feature for compatibility with older GPUs (e.g., Intel UHD 620)
# This must be called before the first Renderer is created.
# Some advanced pygfx features may not work without this feature.
try:
    enable_wgpu_features("!float32-filterable")
except Exception:
    pass  # Feature already configured or other issue

# Track if we've already warned about wgpu/EGL issues
_wgpu_warning_shown = False


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


def _forward_events(
    controller: gfx.OrbitController,
    viewport: gfx.Viewport,
    size: tuple[int, int],
) -> None:
    """
    Forward ImGui mouse/keyboard events to pygfx OrbitController when widget is hovered.
    
    This enables interactive camera controls (orbit, pan, zoom) to work
    with mouse drag, scroll, etc.
    """
    if not imgui.is_item_hovered():
        return
    
    io = imgui.get_io()
    
    # Calculate mouse position relative to widget (top-left origin)
    item_min = imgui.get_item_rect_min()
    mouse_x = io.mouse_pos.x - item_min.x
    mouse_y = io.mouse_pos.y - item_min.y
    
    # pygfx uses top-left origin (same as imgui), no flip needed
    pos = (mouse_x, mouse_y)
    
    # Build event dict base
    base_event = {
        "x": pos[0],
        "y": pos[1],
        "modifiers": [],
    }
    
    # Add modifiers
    if io.key_shift:
        base_event["modifiers"].append("Shift")
    if io.key_ctrl:
        base_event["modifiers"].append("Control")
    if io.key_alt:
        base_event["modifiers"].append("Alt")
    base_event["modifiers"] = tuple(base_event["modifiers"])
    
    # Button mapping: ImGui (0=left, 1=right, 2=middle) -> pygfx button numbers
    button_map = {0: 1, 1: 2, 2: 3}
    
    # Mouse press events
    for imgui_btn, pygfx_btn in button_map.items():
        if imgui.is_mouse_clicked(imgui_btn):
            event = gfx.PointerEvent(
                type="pointer_down",
                x=pos[0],
                y=pos[1],
                button=pygfx_btn,
                modifiers=base_event["modifiers"],
            )
            controller.handle_event(event, viewport)
    
    # Mouse release events
    for imgui_btn, pygfx_btn in button_map.items():
        if imgui.is_mouse_released(imgui_btn):
            event = gfx.PointerEvent(
                type="pointer_up",
                x=pos[0],
                y=pos[1],
                button=pygfx_btn,
                modifiers=base_event["modifiers"],
            )
            controller.handle_event(event, viewport)
    
    # Mouse move events (for drag)
    # Check if any button is down
    buttons_down = [btn for imgui_btn, btn in button_map.items() if io.mouse_down[imgui_btn]]
    if buttons_down or True:  # Always send move for hover effects
        event = gfx.PointerEvent(
            type="pointer_move",
            x=pos[0],
            y=pos[1],
            button=buttons_down[0] if buttons_down else 0,
            modifiers=base_event["modifiers"],
        )
        controller.handle_event(event, viewport)
    
    # Mouse wheel events
    wheel_y = io.mouse_wheel
    wheel_x = io.mouse_wheel_h
    if wheel_x != 0 or wheel_y != 0:
        event = gfx.WheelEvent(
            type="wheel",
            x=pos[0],
            y=pos[1],
            dx=wheel_x * 100,  # Scale to reasonable values
            dy=wheel_y * 100,
            modifiers=base_event["modifiers"],
        )
        controller.handle_event(event, viewport)


def pygfx_canvas(
    gui: Any,
    state: Any,
    canvas_id: str,
    on_init: Callable[[gfx.Scene, gfx.Viewport], None] | None = None,
) -> None:
    """
    Embed a pygfx Scene as an ImGui widget.
    
    Use inside an ImGui window; the canvas fills the entire content region.
    The Scene is accessible at gui.pygfx_scenes[canvas_id].
    
    Mouse and keyboard events are forwarded to pygfx's OrbitController when
    the widget is hovered, enabling interactive camera controls.

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
        (scene, viewport) as arguments. Use this to add objects to the scene.
        
    Notes
    -----
    pygfx requires Vulkan support or a compatible wgpu backend. On systems with
    only OpenGL/EGL (e.g., some Intel integrated GPUs), wgpu's EGL context may
    conflict with GLFW's OpenGL context. If you encounter crashes, use
    vispy_canvas instead.
    """
    global _wgpu_warning_shown
    registry = gui._pygfx_canvases
    gui_ctx = gui.window

    # Compute target size from available ImGui region
    avail = imgui.get_content_region_avail()
    display_size = (max(1, int(avail.x)), max(1, int(avail.y)))

    # Create on first use
    if canvas_id not in registry:
        try:
            # Create offscreen canvas for rendering
            canvas = RenderCanvas(size=display_size, pixel_ratio=1)
            renderer = gfx.renderers.WgpuRenderer(canvas)
        except Exception as e:
            if not _wgpu_warning_shown:
                logger.error(
                    "Failed to create pygfx renderer. This may be due to wgpu's "
                    "OpenGL/EGL backend conflicting with GLFW. Consider using "
                    "vispy_canvas instead. Error: %s", e
                )
                _wgpu_warning_shown = True
            # Show error message in the widget area
            imgui.text_colored(imgui.ImVec4(1, 0.3, 0.3, 1), f"pygfx error: {e}")
            return
        
        # Create scene with default background
        scene = gfx.Scene()
        scene.add(gfx.Background.from_color("#1a1a2e", "#16213e"))
        
        # Create camera and controller
        camera = gfx.PerspectiveCamera(70, aspect=display_size[0] / display_size[1])
        camera.local.position = (0, 0, 5)
        
        # Create viewport
        viewport = gfx.Viewport(renderer)
        
        # Create orbit controller for interactivity
        controller = gfx.OrbitController(camera, register_events=False)
        
        # Add default lighting
        scene.add(gfx.AmbientLight(intensity=0.4))
        directional = gfx.DirectionalLight(intensity=0.6)
        directional.local.position = (3, 5, 7)
        scene.add(directional)

        # Run user init callback
        if on_init is not None:
            on_init(scene, viewport)

        # Create texture in GUI context
        glfw.make_context_current(gui_ctx)
        tex_id = _create_texture(display_size)
        tex_ref = _make_imtexture_ref(tex_id)

        registry[canvas_id] = {
            "canvas": canvas,
            "renderer": renderer,
            "scene": scene,
            "camera": camera,
            "viewport": viewport,
            "controller": controller,
            "tex_id": tex_id,
            "tex_ref": tex_ref,
            "display_size": display_size,
        }
        gui.pygfx_scenes[canvas_id] = scene

    entry = registry[canvas_id]
    canvas: RenderCanvas = entry["canvas"]
    renderer: gfx.renderers.WgpuRenderer = entry["renderer"]
    scene: gfx.Scene = entry["scene"]
    camera: gfx.PerspectiveCamera = entry["camera"]
    viewport: gfx.Viewport = entry["viewport"]
    controller: gfx.OrbitController = entry["controller"]

    # Resize canvas and texture if needed
    if display_size != entry["display_size"]:
        # Resize the offscreen canvas
        canvas._rc_set_logical_size(*display_size)
        
        # Update camera aspect ratio
        camera.aspect = display_size[0] / display_size[1]
        
        # Create new texture before deleting old one
        glfw.make_context_current(gui_ctx)
        new_tex = _create_texture(display_size)
        old_tex = entry["tex_id"]
        entry["tex_id"] = new_tex
        entry["tex_ref"] = _make_imtexture_ref(new_tex)
        entry["display_size"] = display_size
        gl.glDeleteTextures([old_tex])

    # Request a render
    canvas.request_draw(lambda: renderer.render(scene, camera))
    
    # Get the rendered frame as numpy array (RGBA, top-left origin)
    frame = np.asarray(canvas.draw())
    
    # Ensure we are back on the GUI context before touching GL
    glfw.make_context_current(gui_ctx)

    # Upload to texture (pygfx already uses top-left origin, no flip needed)
    _upload_rgba(entry["tex_id"], frame)

    # Draw as an ImGui image
    imgui.image(
        entry["tex_ref"],
        imgui.ImVec2(float(display_size[0]), float(display_size[1])),
    )

    # Forward mouse/keyboard events to pygfx for interactivity
    _forward_events(controller, viewport, display_size)
