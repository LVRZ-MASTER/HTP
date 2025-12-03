# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_submodules

# Directorio base: asumimos que lanzas pyinstaller desde C:\HTP
BASE_DIR = os.getcwd()

# Paquetes que a veces necesitan ayuda con PyInstaller
hidden_imports = []
hidden_imports += collect_submodules("ultralytics")
hidden_imports += collect_submodules("cv2")
hidden_imports += collect_submodules("easyocr")
hidden_imports += collect_submodules("dxcam")
hidden_imports += collect_submodules("fastapi")
hidden_imports += collect_submodules("uvicorn")
hidden_imports += collect_submodules("eval7")
hidden_imports += collect_submodules("pygetwindow")

# Archivos de datos a incluir en el bundle:
datas = [
    # Config principal y charts
    (os.path.join("config", "config.json"), "config"),
    (os.path.join("config", "preflop_charts.json"), "config"),

    # Archivos de interfaz
    ("interface.css", "."),
    ("interface.html", "."),
    ("icoRGB.ico", "."),

    # Plugins completos (directorio entero)
    ("plugins", "plugins"),
]

# Si quieres incluir también el modelo YOLO dentro del exe, puedes
# descomentar estas líneas (ojo que puede ser muy pesado):
#
# datas.append(
#     (
#         os.path.join(
#             "yoloDS", "runs", "detect", "HTP_v11_final", "weights", "best_openvino_model"
#         ),
#         os.path.join(
#             "yoloDS", "runs", "detect", "HTP_v11_final", "weights", "best_openvino_model"
#         ),
#     )
# )

block_cipher = None

a = Analysis(
    ["htp.py"],
    pathex=[BASE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HTP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Cambia a True si quieres ver la consola
    icon="icoRGB.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HTP",
)
