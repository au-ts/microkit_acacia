#
# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause
#
{
  python3Packages,
  nix-gitignore,
}:

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
    python3Packages.libfdt
  ];
  pythonRelaxDeps = true;
  pythonImportsCheck = [ "acacia" ];
}
