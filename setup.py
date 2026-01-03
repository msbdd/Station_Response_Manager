from cx_Freeze import setup, Executable
import sys
import os
from pathlib import Path
import matplotlib
import obspy

mpl_data_path = matplotlib.get_data_path()
sys.setrecursionlimit(8000)
#sys.path.insert(0, 'src')

obsipy_data_dir = os.path.join(
    os.path.dirname(obspy.__file__), "imaging", "data"
    )

site_packages = next(p for p in sys.path if 'site-packages' in p)
dist_info = next(Path(site_packages).glob("obspy-*.dist-info"))

exe = Executable(
    script=os.path.join("app.py"),
    base="Win32GUI" if sys.platform == "win32" else None,
    target_name="SRM",
)

setup(
    name="Station Responce Manager",
    version="__VERSION__",
    description="A utility for managing seismic station responces",
    options={
        "build_exe": {
            "packages": ["obspy", "matplotlib", "numpy",
                         "PyQt5.QtWidgets", "os", "pathlib"],
            "excludes": [],
            "includes": [],
            "include_files": [
                (str(dist_info), f"lib/{dist_info.name}"),
                (mpl_data_path, "lib/matplotlib/mpl-data"),
                (obsipy_data_dir, "lib/obspy/imaging/data"),
                ("SRM_gui/map_template.html", "SRM_gui/map_template.html"),
                ("resources/icon.ico", "resources/icon.ico"),
                ("LICENSE", "LICENSE"),
            ],
            "build_exe": "build/Station_Response_Manager"
        }
    },
    executables=[exe],
)
