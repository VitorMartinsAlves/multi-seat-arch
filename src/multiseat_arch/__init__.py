__version__ = "0.8.0-exp10"

# Keep target-host compatibility fixes active regardless of which entry point
# imports the package (CLI, GUI helpers, hotplug watcher or tests).
from . import backend as _backend
from .runtime_patch import install as _install_runtime_patch
from .runtime_patch_v2 import install as _install_runtime_patch_v2
from .runtime_patch_v3 import install as _install_runtime_patch_v3
from .runtime_patch_v4 import install as _install_runtime_patch_v4
from .runtime_patch_v5 import install as _install_runtime_patch_v5
from .runtime_patch_v6 import install as _install_runtime_patch_v6
from .runtime_patch_v7 import install as _install_runtime_patch_v7
from .runtime_patch_v8 import install as _install_runtime_patch_v8
from .runtime_patch_v9 import install as _install_runtime_patch_v9

_install_runtime_patch(_backend)
_install_runtime_patch_v2(_backend)
_install_runtime_patch_v3(_backend)
_install_runtime_patch_v4(_backend)
_install_runtime_patch_v5(_backend)
_install_runtime_patch_v6(_backend)
_install_runtime_patch_v7(_backend)
_install_runtime_patch_v8(_backend)
_install_runtime_patch_v9(_backend)
