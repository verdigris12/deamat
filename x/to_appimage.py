#!/usr/bin/env python3

import os
import sys
import subprocess
import shutil

def create_appimage(script_path, venv_path):
    if not os.path.isfile(script_path):
        print(f"Error: {script_path} does not exist.")
        sys.exit(1)

    if not os.path.isdir(venv_path):
        print(f"Error: {venv_path} does not exist.")
        sys.exit(1)

    appdir = "AppDir"
    if os.path.exists(appdir):
        shutil.rmtree(appdir)
    os.makedirs(appdir)

    # Copy the virtual environment
    shutil.copytree(venv_path, os.path.join(appdir, "venv"))

    # Copy the script
    shutil.copy(script_path, os.path.join(appdir, "app.py"))

    # Create AppRun
    apprun_content = f"""#!/bin/bash
HERE="$(dirname "$(readlink -f "${{0}}")")"
export PATH="${{HERE}}/venv/bin:$PATH"
exec python3 "${{HERE}}/app.py" "$@"
"""
    with open(os.path.join(appdir, "AppRun"), "w") as f:
        f.write(apprun_content)
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)

    # Create desktop entry
    desktop_entry = f"""[Desktop Entry]
Type=Application
Name=MyApp
Exec=AppRun
Icon=app
Terminal=false
"""
    with open(os.path.join(appdir, "myapp.desktop"), "w") as f:
        f.write(desktop_entry)

    # Create a dummy icon
    with open(os.path.join(appdir, "app.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06\x00\x00\x00\x1f\xf3\xff\xa0\x00\x00\x00\x19tEXtSoftware\x00Adobe ImageReadyq\xc9e<\x00\x00\x00\x0cIDATx\xdacddbf\xa0\x040Q\x00\x00\x00\x82\x00\x01\x0e\x1d\x02\x0e\x00\x00\x00\x00IEND\xaeB`\x82")

    # Download appimagetool
    if not os.path.isfile("appimagetool-x86_64.AppImage"):
        subprocess.run(["wget", "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"])
        os.chmod("appimagetool-x86_64.AppImage", 0o755)

    # Create the AppImage
    subprocess.run(["./appimagetool-x86_64.AppImage", appdir])

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: to_appimage.py <script_path> <venv_path>")
        sys.exit(1)

    script_path = sys.argv[1]
    venv_path = sys.argv[2]

    create_appimage(script_path, venv_path)
