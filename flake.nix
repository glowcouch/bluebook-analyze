{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        py = pkgs.python3.withPackages (ps: with ps; [
          (opencv4.override { enableGtk3 = true; })  # GTK build so cv2.imshow/selectROI work
          numpy
          pytesseract
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [ 
            py
            fd
          ];
        };
      });
}
