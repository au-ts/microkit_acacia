# Contributing to Acacia

## Developing

Make sure you set up a venv as described in the README using the `dev-requirements.txt` pip deps file.

## Pull requests

Before a PR can be merged, the following criteria must be satisfied:
* All code is formatted with `black` and passes the CI linter check.
* All code is appropriately typed and passes `mypy`. Run `mypy acacia` from the root directory of the repository to check.
* All unit tests must pass when running `pytest`. Do not remove tests unless they are totally redundant.
* Add unit tests if you add anything sensitive to the correctness of Acacia.
* Ensure all examples still work.
* Raise a RFC in a GitHub issue if you are pitching a breaking change or major API change.
* Ensure documentation is updated if you make a change that affects the API or usage of Acacia.
* All other CI passes must complete.

## Tips

* The Python REPL is extremely helpful for debugging Acacia.
* Use the seL4 Device Driver Framework as a test platform - it contains several large and complex Acacia subsystems.
* When dealing with Microkit primitives: always try and preserve the default behaviour of the Microkit where it appears in the Acacia API. E.g. channels default to permit notifications and disallow PPCs.
* Do not break the subsystem abstraction!
* Having a friendly, pleasant API is a critical goal for Acacia. Don't be afraid to introduce metaprogramming features (e.g. decorators) where they make sense.
