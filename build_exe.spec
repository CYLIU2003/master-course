# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for master-course run_app.py
# Usage: pyinstaller build_exe.spec

a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include configuration files
        ('config', 'config'),
        ('constant', 'constant'),
        ('data/built', 'data/built'), # Needed for catalog runtime datasets
        ('data/catalog-fast', 'data/catalog-fast'), # Needed for route inventory and normalized catalog fallbacks
        ('data/external', 'data/external'),
        ('data/seed', 'data/seed'),
        ('schema', 'schema'),
        ('app', 'app'),
        # Include app resources if needed
    ],
    hiddenimports=[
        # BFF and FastAPI
        'bff',
        'bff.main',
        'bff.routers',
        'bff.services',
        'bff.mappers',
        'bff.middleware',
        'bff.store',
        'bff.utils',
        'bff.errors',
        'bff.dependencies',
        # Core modules
        'src',
        'src.dispatch',
        'src.dispatch.models',
        'src.optimization',
        'src.pipeline',
        'src.constraints',
        'src.schemas',
        # Tools and UI
        'tools',
        'tools.scenario_backup_tk',
        # FastAPI and uvicorn dependencies
        'fastapi',
        'uvicorn',
        'uvicorn.config',
        'uvicorn.server',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.lifespan',
        'uvicorn.middleware',
        # Starlette and async
        'starlette',
        'starlette.applications',
        'starlette.responses',
        'starlette.routing',
        'starlette.middleware',
        # HTTP client
        'urllib3',
        # Scientific stack
        'pandas',
        'pyarrow',
        # Standard library often missed
        'tkinter',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'tkinter.ttk',
        'json',
        'sqlite3',
        'threading',
        'asyncio',
        'multiprocessing',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[
        'pytest',
        'debugpy',
        'IPython',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MasterCourseApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keeps console open to see backend logs. Set to False for GUI-only.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MasterCourseApp',
)
