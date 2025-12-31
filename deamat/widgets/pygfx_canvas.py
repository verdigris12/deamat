# pygfx widget for deamat with zerocopy texture sharing
# Renders a pygfx Scene to a wgpu texture and displays it via imgui.image()

from typing import Any, Callable
import pygfx as gfx
from imgui_bundle import imgui


class _FakeRenderer:
    """A minimal renderer-like object that does nothing on request_draw()."""
    
    def request_draw(self) -> None:
        # We're already in a render loop, so this is a no-op
        pass


class _FakeViewport:
    """A minimal viewport-like object for pygfx controllers.
    
    pygfx controllers expect a viewport with `rect`, `is_inside()` method,
    and a `renderer` attribute with `request_draw()`.
    """
    
    def __init__(self, width: int, height: int):
        self._rect = (0, 0, width, height)
        self.renderer = _FakeRenderer()
    
    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self._rect
    
    def is_inside(self, x: float, y: float) -> bool:
        rx, ry, rw, rh = self._rect
        return rx <= x < rx + rw and ry <= y < ry + rh


def _handle_imgui_events(
    entry: dict,
    width: int,
    height: int,
    image_pos: tuple[float, float],
) -> None:
    """Handle imgui mouse events and forward to pygfx controller.
    
    Parameters
    ----------
    entry : dict
        The canvas registry entry containing controller, camera, etc.
    width : int
        Canvas width in pixels.
    height : int
        Canvas height in pixels.
    image_pos : tuple[float, float]
        Top-left position of the image widget in screen coordinates.
    """
    controller = entry.get("controller")
    if controller is None:
        return
    
    # Only handle events if the image is hovered
    if not imgui.is_item_hovered():
        return
    
    io = imgui.get_io()
    mouse_pos = imgui.get_mouse_pos()
    
    # Calculate relative position within canvas
    rel_x = mouse_pos.x - image_pos[0]
    rel_y = mouse_pos.y - image_pos[1]
    
    # Create viewport for controller
    viewport = _FakeViewport(width, height)
    
    # Track button states
    buttons_down = []
    if imgui.is_mouse_down(imgui.MouseButton_.left):
        buttons_down.append(1)
    if imgui.is_mouse_down(imgui.MouseButton_.right):
        buttons_down.append(2)
    if imgui.is_mouse_down(imgui.MouseButton_.middle):
        buttons_down.append(3)
    
    # Get modifiers
    modifiers = []
    if io.key_shift:
        modifiers.append("Shift")
    if io.key_ctrl:
        modifiers.append("Control")
    if io.key_alt:
        modifiers.append("Alt")
    
    # Handle mouse button events
    for btn_idx, btn in enumerate([imgui.MouseButton_.left, imgui.MouseButton_.right, imgui.MouseButton_.middle]):
        btn_num = btn_idx + 1
        
        if imgui.is_mouse_clicked(btn):
            event = gfx.PointerEvent(
                type="pointer_down",
                x=rel_x,
                y=rel_y,
                button=btn_num,
                buttons=tuple(buttons_down),
                modifiers=tuple(modifiers),
            )
            controller.handle_event(event, viewport)
        
        if imgui.is_mouse_released(btn):
            event = gfx.PointerEvent(
                type="pointer_up",
                x=rel_x,
                y=rel_y,
                button=btn_num,
                buttons=tuple(buttons_down),
                modifiers=tuple(modifiers),
            )
            controller.handle_event(event, viewport)
    
    # Handle mouse move (when any button is down for drag)
    if any(buttons_down):
        event = gfx.PointerEvent(
            type="pointer_move",
            x=rel_x,
            y=rel_y,
            button=0,
            buttons=tuple(buttons_down),
            modifiers=tuple(modifiers),
        )
        controller.handle_event(event, viewport)
    
    # Handle mouse wheel
    wheel_y = io.mouse_wheel
    wheel_x = io.mouse_wheel_h
    if wheel_y != 0 or wheel_x != 0:
        event = gfx.WheelEvent(
            type="wheel",
            x=rel_x,
            y=rel_y,
            dx=wheel_x * 0.1,  # Scale to reasonable values
            dy=wheel_y * 0.1,
            button=0,
            buttons=tuple(buttons_down),
            modifiers=tuple(modifiers),
        )
        controller.handle_event(event, viewport)


def pygfx_canvas(
    gui: Any,
    state: Any,
    canvas_id: str,
    on_init: Callable[[gfx.Scene, gfx.PerspectiveCamera], None] | None = None,
    controller: gfx.Controller | None = None,
) -> None:
    """
    Embed a pygfx 3D scene into an ImGui window using zerocopy texture sharing.

    The scene is rendered to a pygfx Texture, and the underlying wgpu texture view
    is registered with the imgui backend for direct display without pixel copying.

    Parameters
    ----------
    gui : GUI
        The deamat GUI instance.
    state : GUIState
        The application state.
    canvas_id : str
        Unique identifier for this canvas.
    on_init : callable, optional
        Callback invoked once when the scene is created, receiving
        (scene, camera) as arguments. Use this to add objects, lights, etc.
    controller : gfx.Controller, optional
        A pygfx controller (e.g., OrbitController, TrackballController) for
        camera interaction. If provided, mouse events will be forwarded to it.
    """
    registry = gui._pygfx_scenes

    # Get available region size from ImGui
    avail = imgui.get_content_region_avail()
    width = max(1, int(avail.x))
    height = max(1, int(avail.y))

    if canvas_id not in registry:
        # Create pygfx scene and camera
        scene = gfx.Scene()
        camera = gfx.PerspectiveCamera(45, width / height if height > 0 else 1)

        # Create a pygfx Texture as render target
        # pygfx will create the underlying wgpu texture automatically
        gfx_texture = gfx.Texture(
            data=None,
            dim=2,
            size=(width, height, 1),
            format="rgba8unorm",
        )

        # Create a dedicated renderer for this canvas that targets the texture
        renderer = gfx.WgpuRenderer(gfx_texture)

        # Force the texture to be created by accessing internal wgpu object
        # The renderer creates the wgpu texture lazily, so we need to trigger it
        renderer.render(scene, camera, flush=True)

        # Get the wgpu texture view and register with imgui
        wgpu_texture = gfx_texture._wgpu_object
        texture_view = wgpu_texture.create_view()
        tex_ref = gui.gui_renderer.backend.register_texture(texture_view)

        registry[canvas_id] = {
            "scene": scene,
            "camera": camera,
            "renderer": renderer,
            "gfx_texture": gfx_texture,
            "texture_view": texture_view,
            "tex_ref": tex_ref,
            "size": (width, height),
            "inited": False,
            "controller": None,
        }
        gui.scenes[canvas_id] = scene

    entry = registry[canvas_id]
    scene = entry["scene"]
    camera = entry["camera"]
    renderer = entry["renderer"]

    # Update controller reference (may change between frames)
    if controller is not None:
        if entry["controller"] is not controller:
            entry["controller"] = controller
            # Register camera with controller if not already done
            controller.add_camera(camera)

    # Run user init callback once
    if not entry["inited"] and on_init is not None:
        on_init(scene, camera)
        entry["inited"] = True

    # Handle resize
    if (width, height) != entry["size"] and width > 0 and height > 0:
        # Unregister old texture
        gui.gui_renderer.backend.unregister_texture(entry["tex_ref"])

        # Create new pygfx texture with new size
        gfx_texture = gfx.Texture(
            data=None,
            dim=2,
            size=(width, height, 1),
            format="rgba8unorm",
        )

        # Create new renderer targeting the new texture
        renderer = gfx.WgpuRenderer(gfx_texture)

        # Force texture creation
        renderer.render(scene, camera, flush=True)

        # Get the wgpu texture view and register with imgui
        wgpu_texture = gfx_texture._wgpu_object
        texture_view = wgpu_texture.create_view()
        tex_ref = gui.gui_renderer.backend.register_texture(texture_view)

        # Update camera aspect ratio
        camera.fov = 45
        if hasattr(camera, "aspect"):
            camera.aspect = width / height

        entry["renderer"] = renderer
        entry["gfx_texture"] = gfx_texture
        entry["texture_view"] = texture_view
        entry["tex_ref"] = tex_ref
        entry["size"] = (width, height)

    # Update camera view size for proper projection
    camera.set_view_size(width, height)

    # Render pygfx scene to the texture
    renderer.render(scene, camera, flush=True)

    # Get cursor position before drawing image (for event handling)
    cursor_pos = imgui.get_cursor_screen_pos()
    image_pos = (cursor_pos.x, cursor_pos.y)

    # Display texture in imgui (ZEROCOPY - just passes the texture reference)
    imgui.image(
        entry["tex_ref"],
        imgui.ImVec2(float(width), float(height)),
    )

    # Handle mouse events for controller
    _handle_imgui_events(entry, width, height, image_pos)
