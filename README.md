# Seismic Response Manager

![License: GPL v3](https://img.shields.io/badge/License-GPLv3-brightgreen.svg)
![Code style: flake8](https://img.shields.io/badge/Code%20style-flake8-brightgreen)

[![Build Windows](https://github.com/msbdd/Station_Response_Manager/actions/workflows/Distribute_Windows.yml/badge.svg)](https://github.com/msbdd/Station_Response_Manager/actions/workflows/Distribute_Windows.yml)
[![Build Linux AppImage](https://github.com/msbdd/Station_Response_Manager/actions/workflows/Distribute_Linux_AppImage.yml/badge.svg)](https://github.com/msbdd/Station_Response_Manager/actions/workflows/Distribute_Linux_AppImage.yml)

**Seismic Response Manager** is a user-friendly tool for viewing, editing, and managing seismic station metadata in both [FDSN StationXML](https://www.fdsn.org/xml/station/) and [dataless SEED](https://ds.iris.edu/ds/nodes/dmc/data/formats/dataless-seed/) formats.

## Motivation

This project is inspired by the [IRIS PDCC (Portable Data Collection Center)](https://ds.iris.edu/ds/nodes/dmc/software/downloads/pdcc/), aiming to provide a modern, intuitive alternative for network operators, researchers, and data managers.

While the Java version of PDCC still works, I experienced issues:
- Crashes when loading valid custom `.RESP` files (files that [ObsPy](https://docs.obspy.org/) handles without problems)
- No StationXML support
- No openly available repo with issue list, etc

StationXML is a great format for managing station metadata — but editing it manually in a text editor isn't always comfortable. **Seismic Response Manager** is designed for usability, making common tasks easier, safer, and more convenient.

## Documentation

- [Quick Start Guide](docs/quick_start.md)

## Status

Optimized primarily for graphical interface users, this project emphasizes intuitive usability and straightforward design over complex technical requirements. In a nutshell, that’s just a polite way of saying it’s another text editor made specifically for StationXML files. Okay, it also has a miniSEED reader, so maybe it's slightly more than a text editor, but we still keep things simple.

## Dependencies and attribution

### Core libraries

- **[PyQt5](https://riverbankcomputing.com/software/pyqt/)** — GPL v3. GUI framework.
- **[PyQtWebEngine](https://riverbankcomputing.com/software/pyqtwebengine/)** — GPL v3. Embedded web view for the station map.
- **[ObsPy](https://docs.obspy.org/)** — LGPL v3. Seismic data processing.
- **[matplotlib](https://matplotlib.org/)** — PSF License. Plotting and visualization.
- **[NumPy](https://numpy.org/)** — BSD. Numerical computing.

### Build and packaging

- **[cx_Freeze](https://cx-freeze.readthedocs.io/)** — PSF License. Windows executable packaging.
- **[AppImageKit](https://github.com/AppImage/AppImageKit)** — MIT. Linux AppImage packaging.

### Bundled assets (offline map support)

- **[Leaflet](https://leafletjs.com/)** — BSD-2-Clause. Interactive station map.
- **[OpenTopoMap](https://opentopomap.org/) tiles** (zoom levels 0–3) — map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, SRTM; map style © OpenTopoMap ([CC-BY-SA](https://creativecommons.org/licenses/by-sa/3.0/)). Pre-cached to allow basic map functionality without an internet connection.
