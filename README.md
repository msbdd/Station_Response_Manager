# Seismic Response Manager
![License: GPL v3](https://img.shields.io/badge/License-GPLv3-brightgreen.svg)
![Code style: flake8](https://img.shields.io/badge/Code%20style-flake8-brightgreen)

[![Station_Response_Manager Build Windows](https://github.com/msbdd/Station_Response_Manager/actions/workflows/Distribute_Windows.yml/badge.svg)](https://github.com/msbdd/Station_Response_Manager/actions/workflows/Distribute_Windows.yml)

**Seismic Response Manager** is a user-friendly tool for viewing, editing, and managing seismic station metadata in both [FDSN StationXML](https://www.fdsn.org/xml/station/) and [dataless SEED](https://ds.iris.edu/ds/nodes/dmc/data/formats/dataless-seed/) formats.

This project is inspired by the [IRIS PDCC (Portable Data Collection Center)](https://ds.iris.edu/ds/nodes/dmc/software/downloads/pdcc/), aiming to provide a modern, intuitive alternative for network operators, researchers, and data managers.  
While the Java version of PDCC still works, I have experienced crashes, lack of support for custom `.RESP` files (crashed while trying to load a valid file that could be loaded in [ObsPy](https://docs.obspy.org/)), and missing StationXML support.

StationXML is a great format for managing station metadata — but editing it manually in a text editor isn't always comfortable for users.  

**Seismic Response Manager** is designed for usability, making common tasks easier, safer, and more convenient.

Currently trying to create a first MVP that could be used.
Currently built only for Windows as Linux users could easily run it.
Packaging will be considered once the app is good enough to use.
Intended for both command-line and graphical interface users.
