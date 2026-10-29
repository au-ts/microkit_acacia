#!/bin/bash
# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

# Build the sphinx site once.
set -e
cd "$(dirname "$0")"
python3 -m sphinx -b html . _build/html "$@"
