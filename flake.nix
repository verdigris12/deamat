{
  description = "Deamat";

  inputs = {
    nixpkgs.url = "nixpkgs/nixos-24.05";
  };

  outputs = { self, nixpkgs }: 
  let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; };
    title = "Deamat";
  in
  {

    devShells.${system}.default = pkgs.mkShell {
      LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath (with pkgs; [
        zlib
        zstd
        stdenv.cc.cc
        curl
        openssl
        attr
        libssh
        bzip2
        libxml2
        acl
        libsodium
        util-linux
        xz
        # For IMGUI
        xorg.libXext
        xorg.libX11
        libGL
        libGLU
        glib
      ]);

      buildInputs = with pkgs; [
        zlib
        zstd
        stdenv.cc.cc
        curl
        openssl
        attr
        libssh
        bzip2
        libxml2
        acl
        libsodium
        util-linux
        xz
        systemd
        (pkgs.python311.withPackages (ps: with ps; [
          pysocks
          pip
          pyopengl
          matplotlib
         ]))
      ];

      shellHook = ''
        export DEVSHELL="${title}"
        '';
    };
  };
}
