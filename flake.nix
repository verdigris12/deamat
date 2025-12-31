{
  description = "Deamat: imgui+matplotlib boilerplate";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/11cb3517b3af6af300dd6c055aeda73c9bf52c48";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll  = f: builtins.listToAttrs (map (s: { name = s; value = f s; }) systems);
    in {
      devShells = forAll (system:
        let
          pkgs = import nixpkgs { inherit system; };
          fhs  = pkgs.buildFHSEnvBubblewrap {
            name = "deamat-fhs";
            targetPkgs = p: with p; [
              # Core
              glibc stdenv.cc.cc.lib zlib
              python312 uv
              pkg-config patchelf bashInteractive

              # Build tools (for packages that need compilation)
              gcc cmake ninja

              # OpenGL/Graphics (for imgui, vispy)
              libGL libGLU mesa

              # X11 (for GLFW) - includes .dev for headers
              xorg.libX11 xorg.libX11.dev xorg.xorgproto
              xorg.libXi xorg.libXrandr xorg.libXext 
              xorg.libXinerama xorg.libXxf86vm xorg.libXcursor

              # For vispy fonts
              freetype fontconfig

              # For numpy (if building from source)
              blas lapack
            ];
            runScript = "${pkgs.bashInteractive}/bin/bash";

            profile = ''
              export DEVSHELL="DEAMAT"
              if [ ! -d .venv ]; then
                uv venv
              fi
              source .venv/bin/activate
              echo "($(python -V)) venv active → use: uv pip install <pkg>"
            '';
          };
        in {
          default = fhs.env;
        });
    };
}
