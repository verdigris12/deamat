{
  description = "Deamat: imgui+matplotlib boilerplate";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/11cb3517b3af6af300dd6c055aeda73c9bf52c48";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll  = f: builtins.listToAttrs (map (s: { name = s; value = f s; }) systems);
    in {
      packages = forAll (system:
        let
          pkgs = import nixpkgs { inherit system; };
          fhs  = pkgs.buildFHSEnvBubblewrap {
            name = "deamat-fhs";
            targetPkgs = p: with p; [
              # Core
              glibc stdenv.cc.cc.lib zlib
              python312 uv
              pkg-config patchelf bashInteractive
              vulkan-loader
              vulkan-tools

              # Build tools (for packages that need compilation)
              gcc cmake ninja

              # OpenGL/Graphics (for imgui, vispy)
              libGL libGL.dev libGLU libGLU.dev mesa

              # X11 (for GLFW) - includes .dev for headers
              xorg.libX11 xorg.libX11.dev xorg.xorgproto
              xorg.libXi xorg.libXi.dev
              xorg.libXrandr xorg.libXrandr.dev
              xorg.libXext xorg.libXext.dev
              xorg.libXinerama xorg.libXinerama.dev
              xorg.libXxf86vm xorg.libXcursor xorg.libXcursor.dev
              xorg.libXrender xorg.libXrender.dev
              xorg.libXfixes xorg.libXfixes.dev

              # For vispy fonts
              freetype fontconfig

              # For numpy (if building from source)
              blas lapack
            ];
            runScript = "${pkgs.bashInteractive}/bin/bash";

            profile = ''
              export DEVSHELL="DEAMAT"
              export CMAKE_ARGS="-DCMAKE_FIND_ROOT_PATH=/ -DCMAKE_PREFIX_PATH=/usr ''${CMAKE_ARGS:-}"
              if [ ! -d .venv ]; then
                uv venv
              fi
              source .venv/bin/activate
              echo "($(python -V)) venv active → use: uv pip install <pkg>"
            '';
          };
        in {
          default = fhs;
        });
      devShells = forAll (system: {
        default = self.packages.${system}.default.env;
      });
      apps = forAll (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/deamat-fhs";
        };
      });
    };
}
