{
  description = "Deamat: imgui+matplotlib boilerplate";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/e2605d0744c2417b09f8bf850dfca42fcf537d34";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        devshellName = "PYTHON";

        pkgs = import nixpkgs { inherit system; };

        pythonNative = pkgs.python311.withPackages (ps: [
          ps.numpy
          ps.lxml
          ps.pysocks
          ps.ipython
          ps.setuptools
          ps.wheel
        ]);

        nativeTools = with pkgs; [ gcc cmake ninja pkg-config ];

        # runtime libraries (zlib + OpenSSL + GCC’s libstdc++ + others)
        # used for building backends
        nativeLibs = with pkgs; [
          zlib
          openssl
          (pkgs.lib.getLib pkgs.stdenv.cc.cc)
          # for numpy
          blas lapack gfortran
          # For imgui
          libGL xorg.libX11 xorg.libXi xorg.libXrandr mesa xorg.libXext libGLU
        ];
      in {
        devShells.default = pkgs.mkShell {
          packages = [ pythonNative pkgs.uv ] ++ nativeTools ++ nativeLibs;

          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath nativeLibs;

          shellHook = ''
          export DEVSHELL=${devshellName}
          export UV_NO_BINARY=1
          export UV_NO_BUILD_ISOLATION=1

          if [ ! -d .venv ]; then
            "${pythonNative}/bin/python" -m venv .venv
          fi
          source .venv/bin/activate
          export UV_PYTHON="$VIRTUAL_ENV/bin/python"

          echo "($(python -V)) venv active → use: uv pip install <pkg>"
          .venv/bin/pip install --upgrade pip setuptools wheel >/dev/null
          '';
        };
      });
}