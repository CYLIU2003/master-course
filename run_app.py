import sys
import os
import builtins

if not hasattr(builtins, 'help'):
    builtins.help = lambda *args, **kwargs: None

import threading
import asyncio
import time
import urllib.request
import multiprocessing
import traceback
import uvicorn
from pathlib import Path

def setup_paths():
    """Ensure PyInstaller paths and project root are correctly handled."""
    import sys
    from pathlib import Path
    import os
    
    # Check if application is running as a PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # sys._MEIPASS is available for both onefile and onedir builds in newer PyInstaller
        if hasattr(sys, '_MEIPASS'):
            base_dir = Path(sys._MEIPASS)
        else:
            base_dir = Path(sys.executable).parent
            
        if str(base_dir) not in sys.path:
            sys.path.insert(0, str(base_dir))
            
        # Change current working directory to the directory where the executable is located
        exe_dir = Path(sys.executable).parent
        os.chdir(str(exe_dir))
        
        # Set an environment variable so BFF knows we are running in bundled mode
        os.environ["MC_BUNDLED_MODE"] = "1"
        os.environ["MC_MEIPASS"] = str(base_dir)
        
        # Force paths so app_cache.py finds the datasets in the Pyinstaller bundle
        os.environ["BUILT_ROOT"] = str(base_dir / "data" / "built")
        # Ensure outputs go to the real user folder, not inside _internal
        out_dir = exe_dir / "outputs"
        scen_dir = out_dir / "scenarios"
        os.environ["SCENARIO_STORE_PATH"] = str(scen_dir)
        os.environ["MC_OUTPUTS_DIR"] = str(out_dir)
        
        # Create output directories if they don't exist yet
        try:
            scen_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

def run_bff_server():
    """Run FastAPI server in a daemon thread using uvicorn.Server"""
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    
    import bff.main
    # Configure the uvicorn server
    config = uvicorn.Config(
        app=bff.main.app, # Use app instance directly to avoid import issues in PyInstaller
        host="127.0.0.1",
        port=8000,
        log_level="info",
        # Important for PyInstaller: do not use reload.
        reload=False
    )
    server = uvicorn.Server(config)
    
    def run_server():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())
    
    # Start in a daemon thread
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    
    return server, thread, loop

def shutdown_bff_server(server, thread, loop, timeout=5):
    """Gracefully shut down the server"""
    print("Terminating backend server...")
    server.should_exit = True
    
    # Wake up the event loop if it's blocked
    loop.call_soon_threadsafe(lambda: None)
    
    try:
        thread.join(timeout=timeout)
        if thread.is_alive():
            print("Warning: server thread did not exit in time")
    except Exception as e:
        print(f"Error stopping server: {e}")

def wait_for_server(url="http://127.0.0.1:8000/api/app/datasets", timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2.0) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"BFF server did not start in time. Checked URL: {url}")

def main():
    multiprocessing.freeze_support()
    setup_paths()

    print("Starting backend server (FastAPI)...")
    server, thread, loop = run_bff_server()
    
    try:
        print("Waiting for backend server to be ready...")
        wait_for_server()
        print("Backend server is ready.")
        
        # Import and start Tkinter UI
        # We put imports here to prevent them slowing down the server startup
        import tkinter as tk
        from tools.scenario_backup_tk import App
        
        print("Starting frontend application (Tkinter)...")
        root = tk.Tk()
        root.protocol("WM_DELETE_WINDOW", root.quit)
        
        app = App(root)
        print("Frontend UI running. Close the window to shut down the application.")
        
        root.mainloop()
        print("Frontend closed.")

    except Exception as e:
        print(f"Error occurred: {e}")
        traceback.print_exc()
        input("Press Enter to exit...")
    finally:
        shutdown_bff_server(server, thread, loop)
        print("Application shutdown complete.")

if __name__ == "__main__":
    main()
