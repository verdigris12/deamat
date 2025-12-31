# VisPy Integration in Deamat: Technical Notes

This document details attempts to optimize the VisPy widget integration in deamat, the challenges encountered, and lessons learned. It's intended to help future developers understand the architecture and avoid repeating failed approaches.

## Current Implementation

The current implementation in `deamat/widgets/vispy_canvas.py` uses a **GPU→CPU→GPU** rendering pipeline:

```
VisPy SceneCanvas → canvas.render() → NumPy array (CPU) → glTexSubImage2D → ImGui texture
```

### How It Works

1. **VisPy Rendering**: `canvas.render()` renders the scene to an internal FBO and calls `glReadPixels` to return a NumPy array (HxWx4 uint8, RGBA, bottom-left origin).

2. **CPU Processing**: The array is flipped vertically with `np.flipud()` to convert from OpenGL's bottom-left origin to ImGui's top-left origin.

3. **Texture Upload**: The flipped array is uploaded to a texture in the GUI's OpenGL context using `glTexSubImage2D`.

4. **Display**: `imgui.image()` displays the texture.

5. **Event Forwarding**: Mouse and keyboard events are translated from ImGui to VisPy's event system when the widget is hovered, enabling interactive camera controls.

### Performance Characteristics

- **`glReadPixels`**: This is the main bottleneck. It forces a GPU pipeline stall as the CPU waits for the GPU to finish rendering before reading pixels back.
- **`np.flipud`**: Creates a copy of the array (though this could be optimized with stride tricks).
- **`glTexSubImage2D`**: Uploads pixels back to GPU. Relatively fast but still involves CPU→GPU transfer.

For a 640x480 canvas, this involves transferring ~1.2MB per frame in each direction.

---

## Failed Optimization Attempt: Direct FBO Render-to-Texture

### Goal

Eliminate the GPU→CPU→GPU roundtrip by having VisPy render directly to a texture that ImGui can display.

### Approach

1. Create an FBO with a color texture attachment in the GUI's OpenGL context
2. Have VisPy render to that FBO
3. Use the texture directly with `imgui.image()`

### Implementation Attempts

#### Attempt 1: Use VisPy's gloo.Texture2D + gloo.FrameBuffer

```python
from vispy import gloo

tex = gloo.Texture2D(shape=(h, w, 4), format='rgba')
depth = gloo.RenderBuffer(shape=(h, w), format='depth')
fbo = gloo.FrameBuffer(color=tex, depth=depth)

canvas.push_fbo(fbo, offset=(0, 0), csize=(w, h))
canvas.on_draw(None)
canvas.pop_fbo()

# Get GL texture handle
gl_tex_id = get_handle_from_vispy(tex)
imgui.image(gl_tex_id, ...)
```

**Problems Encountered:**

1. **GLIR Queue Association**: VisPy uses GLIR (GL Intermediate Representation) - a deferred command queue. gloo objects created outside a canvas have their own GLIR queues that aren't connected to the canvas's queue.

   **Solution**: Associate GLIR queues:
   ```python
   canvas.context.glir.associate(tex._glir)
   canvas.context.glir.associate(fbo._glir)
   ```

2. **GLIR Not Flushing**: `canvas.draw_visual(canvas.scene)` only queues GLIR commands but doesn't flush them to OpenGL. The texture handle doesn't exist until GLIR executes.

   **Solution**: Use `canvas.on_draw(None)` which triggers the full rendering pipeline including GLIR flush.

3. **Empty GLIR Objects**: If there are no visuals to draw, GLIR doesn't flush anything. The `on_init` callback must be called BEFORE the first render to ensure visuals exist.

4. **Getting the GL Handle**: VisPy's gloo objects have internal IDs (`tex.id`) that are NOT OpenGL handles. The actual GL handle is stored in:
   ```python
   parser = canvas.context.shared.parser
   glir_obj = parser._objects[tex.id]
   gl_handle = glir_obj._handle
   ```

#### Attempt 2: The Critical Failure - Context Separation

Even after solving all the above issues, **the texture displayed garbage (ImGui's font atlas)**.

**Root Cause**: OpenGL contexts are isolated. VisPy's `SceneCanvas` creates its own GLFW window with its own GL context. Texture handles are context-local:

- Texture ID 1 in VisPy's context ≠ Texture ID 1 in GUI's context
- When we pass handle "1" to ImGui, it interprets it as texture 1 in the GUI context (which happens to be the font atlas)

**Verification**:
```python
# In VisPy context
canvas.set_current()
vispy_tex = gl.glGenTextures(1)  # Returns 1

# In GUI context  
glfw.make_context_current(gui_window)
gl.glIsTexture(vispy_tex)  # Returns False! Different context.
```

#### Attempt 3: Shared GL Contexts via GLFW

GLFW supports context sharing - pass a share window when creating a new window:

```python
window2 = glfw.create_window(w, h, "title", None, window1)  # Share with window1
```

Textures created in one context ARE valid in the other when contexts are shared.

**Problem**: VisPy's `SceneCanvas.__init__` has a `shared` parameter, but it expects a **VisPy Canvas or GLContext object**, not a raw GLFW window:

```python
canvas = scene.SceneCanvas(shared=gui_window)  # FAILS
# TypeError: shared must be a Canvas, not <class 'glfw.LP__GLFWwindow'>
```

#### Attempt 4: Create Shared Context via Dummy Canvas

Idea: Create a hidden VisPy canvas first, then use it as the shared context for subsequent canvases.

**Not Attempted**: This would require modifying VisPy's GLFW backend to accept an external GLFW window for context sharing, or creating a complex wrapper. The complexity wasn't justified given the working fallback.

---

## Key Technical Insights

### VisPy's Architecture

1. **GLIR (GL Intermediate Representation)**: VisPy doesn't call OpenGL directly. It queues commands in GLIR, which are later flushed to the GPU. This enables:
   - Batching of GL calls
   - Remote rendering (e.g., Jupyter)
   - Platform abstraction

2. **Context Management**: Each `SceneCanvas` owns a `GLContext` which owns a `GLShared` which owns a `GlirParser`. The parser's `_objects` dict maps VisPy internal IDs to actual GL objects.

3. **Backend Abstraction**: VisPy supports multiple backends (Qt, GLFW, SDL2, etc.). The GLFW backend creates its own GLFW window/context.

### OpenGL Context Rules

1. **Context Locality**: GL object names (handles) are only valid in the context where they were created, UNLESS contexts are shared.

2. **Shared Contexts**: When contexts share, they share:
   - Textures
   - Buffer objects
   - Shader programs
   - Renderbuffers
   
   They do NOT share:
   - Framebuffer objects (FBOs)
   - Vertex array objects (VAOs)
   - Query objects

3. **Context Currency**: Only one context can be "current" per thread at a time. `glfw.make_context_current()` switches contexts.

### ImGui Texture Handling

ImGui's `imgui.image()` expects a texture ID valid in the current GL context. The `ImTextureID` wrapper is just a cast of the integer handle.

---

## Potential Future Optimizations

### Option A: Modify VisPy's GLFW Backend

Create a custom GLFW backend that accepts an external GLFW window for context sharing:

```python
# Hypothetical API
canvas = scene.SceneCanvas(
    backend_kwargs={'share_window': gui_window}
)
```

This would require:
1. Forking or monkey-patching `vispy.app.backends._glfw`
2. Modifying `CanvasBackend.__init__` to accept a share window
3. Passing it to `glfw.create_window(..., share=share_window)`

**Complexity**: Medium-High
**Benefit**: True zero-copy rendering

### Option B: Use Pixel Buffer Objects (PBOs)

PBOs can make `glReadPixels` asynchronous:

```python
# Frame N: Start async read into PBO
gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, pbo)
gl.glReadPixels(0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)

# Frame N+1: Map PBO (previous frame's data is ready)
ptr = gl.glMapBuffer(gl.GL_PIXEL_PACK_BUFFER, gl.GL_READ_ONLY)
# Copy to texture...
gl.glUnmapBuffer(gl.GL_PIXEL_PACK_BUFFER)
```

**Complexity**: Medium
**Benefit**: Reduces stalls by pipelining, but still involves CPU

### Option C: Use OpenGL-to-OpenGL Blit

If contexts ARE shared (future), use `glBlitFramebuffer`:

```python
gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, vispy_fbo)
gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, gui_fbo)
gl.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h, gl.GL_COLOR_BUFFER_BIT, gl.GL_LINEAR)
```

**Complexity**: Low (if contexts are shared)
**Benefit**: GPU-only copy, very fast

### Option D: Render to GUI Context Directly

Instead of using VisPy's SceneCanvas, use VisPy's lower-level `gloo` API directly in the GUI's GL context:

```python
glfw.make_context_current(gui_window)
# Use gloo.Program, gloo.VertexBuffer directly
# No SceneCanvas, no separate context
```

**Complexity**: High (lose scene graph, cameras, visuals)
**Benefit**: Full control, no context issues

---

## Current Status

The implementation uses the GPU→CPU→GPU approach with event forwarding. This is correct and functional but not optimal for performance-critical applications.

**What Works**:
- Rendering displays correctly
- Interactive camera controls (drag, zoom, pan)
- Resize handling
- Multiple canvases

**Performance**:
- Acceptable for moderate canvas sizes (< 1024x1024)
- May cause frame drops for large canvases or complex scenes
- The main bottleneck is `canvas.render()` which internally calls `glReadPixels`

---

## References

- [VisPy GLIR Documentation](https://vispy.org/gloo.html)
- [OpenGL Context Sharing](https://www.khronos.org/opengl/wiki/OpenGL_Context#Context_sharing)
- [GLFW Context Guide](https://www.glfw.org/docs/latest/context_guide.html)
- [ImGui Custom Textures](https://github.com/ocornut/imgui/wiki/Image-Loading-and-Displaying-Examples)
