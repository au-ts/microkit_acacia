#
# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
#
{
  stdenv,
  python3Packages,
  nix-gitignore,
}:

let
  libfdt = if stdenv.hostPlatform.isDarwin then
    (python3Packages.libfdt.overrideAttrs (final: prev: {
      postFixup = (prev.postFixup or "") + ''
        install_name_tool -change \
          "@rpath/libfdt.1.dylib" "$out/lib/libfdt.1.dylib" \
          $out/${python3Packages.python.sitePackages}/_libfdt.cpython-*-darwin.so
      '';
      }))
    else python3Packages.libfdt;
in

python3Packages.buildPythonPackage {
  pname = "acacia";
  version = builtins.readFile ./VERSION;
  pyproject = true;

  src = nix-gitignore.gitignoreSourcePure [
    ./.gitignore
  ] ./.;

  build-system = [ python3Packages.setuptools ];
  dependencies = [
    python3Packages.lark
    libfdt
  ];
  pythonRelaxDeps = true;
  pythonImportsCheck = [ "acacia" ];
}
