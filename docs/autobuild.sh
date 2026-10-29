#!/bin/bash
# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

# Serve sphinx site with auto rebuilding
set -e
cd "$(dirname "$0")"
python3 -m sphinx_autobuild . _build/html --watch ../acacia --ignore "$PWD/apidocs" "$@"
