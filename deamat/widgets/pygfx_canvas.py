# pygfx widget for deamat with zerocopy texture sharing
# Renders a pygfx Scene to a wgpu texture and displays it via imgui.image()

from typing import Any, Callable
import pygfx as gfx
from imgui_bundle import imgui


def pygfx_canvas(
    gui: Any,
    state: Any,
    canvas_id: str,
    on_init: Callable[[gfx.Scene, gfx.PerspectiveCamera], None] | None = None,
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
        }
        gui.scenes[canvas_id] = scene

    entry = registry[canvas_id]
    scene = entry["scene"]
    camera = entry["camera"]
    renderer = entry["renderer"]

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

    # Display texture in imgui (ZEROCOPY - just passes the texture reference)
    imgui.image(
        entry["tex_ref"],
        imgui.ImVec2(float(width), float(height)),
    )
