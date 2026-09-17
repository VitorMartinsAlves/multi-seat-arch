__version__ = "0.8.0-exp25"

# Keep target-host compatibility fixes active regardless of which entry point
# imports the package. The established layer order now has one canonical
# registration point so it can be consolidated safely over time.
from . import backend as _backend
from .runtime_stack import install as _install_runtime_stack

_install_runtime_stack(_backend)
