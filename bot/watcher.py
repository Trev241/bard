import time
import subprocess
import threading
import git
import os
import psutil

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

REBOOT_GRACE_PERIOD = 10
MODIFICATION_COOLDOWN_PERIOD = 5
PIP_INSTALL_COMMANDS = [
    ["pip", "install", "discord.py", "-U"],
    ["pip", "install", "-U", "--pre", "yt-dlp[default]"],
]
RESTART_SIGNAL_TRIGGER_FILE = "bot/restart_signal_trigger.flag"


class RestartHandler(FileSystemEventHandler):
    def __init__(self, command, target_file):
        self.command = command
        self.target_file = target_file
        self.process = None
        self.timer = None
        self.repo = git.Repo()
        self.last_pull_time = 0

    def start_process(self):
        """Start the process."""
        self.timer = None  # Reset timer object after restart
        if self.process and self.is_process_running():
            print("Process is already running, terminating it first.")
            self.terminate_process()

        print(f"Starting process: {' '.join(self.command)}")
        self.process = subprocess.Popen(self.command)
        print(f"Process started with PID: {self.process.pid}")

    def is_process_running(self):
        if self.process is None:
            return False
        return self.process.poll() is None

    def restart_process(self):
        """Restart the process."""

        print("Initiating restart...")
        self.terminate_process()

        for cmd in PIP_INSTALL_COMMANDS:
            print(f"Running: {' '.join(cmd)}")
            try:
                result = subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                if result.stdout.strip():
                    print(result.stdout)
                print(f"Finished: {' '.join(cmd)}")
                if "Requirement already satisfied" not in result.stdout:
                    # Something actually installed/upgraded → we’ll need a restart
                    needs_restart = True
            except subprocess.CalledProcessError as e:
                print(f"pip install failed ({' '.join(cmd)}):")
                print(e.stdout)

        time.sleep(1)
        self.start_process()

    def initiate_restart(self):
        if self.timer is None:
            with open("bot/restart_signal.flag", "w") as f:
                f.write("restart")

            print(f"Rebooting in {REBOOT_GRACE_PERIOD} seconds.")
            self.timer = threading.Timer(REBOOT_GRACE_PERIOD, self.restart_process)
            self.timer.start()

    def check_full_restart_signal(self):
        """Check for full restart signal file and act if present."""

        if os.path.exists(RESTART_SIGNAL_TRIGGER_FILE):
            print(f"Detected {RESTART_SIGNAL_TRIGGER_FILE}, initiating full restart...")
            try:
                os.remove(RESTART_SIGNAL_TRIGGER_FILE)  # Clean up signal file
            except Exception as e:
                print(f"Error removing {RESTART_SIGNAL_TRIGGER_FILE}: {e}")

            self.initiate_restart()

    def terminate_process(self):
        """Terminates the process and its children"""

        try:
            proc = psutil.Process(self.process.pid)
            children = proc.children(recursive=True)

            print(f"Terminating process with PID: {self.process.pid}")
            proc.terminate()

            for child in children:
                print(f"Terminating child process with PID: {child.pid}")

            proc.wait(timeout=5)
            print("Process terminated successfully.")
        except psutil.NoSuchProcess:
            print("Process no longer exists")
        except psutil.TimeoutExpired:
            print("Process did not terminate, forcing kill...")
            proc.kill()
            proc.wait(timeout=5)
        except Exception as e:
            print(f"Error terminating processes: {e}")

        self.process = None

    def on_modified(self, event):
        """Handle file modification events by restarting the app if the target file is modified."""
        if os.path.samefile(event.src_path, os.path.relpath(self.target_file)):
            current_time = time.time()

            if current_time - self.last_pull_time < MODIFICATION_COOLDOWN_PERIOD:
                print(
                    f"Ignoring modification in {event.src_path} due to recent git pull (cooldown)."
                )
                return

            print(f"Detected change in {event.src_path}, restarting Flask app.")
            print("Pulling changes...")
            try:
                self.repo.remotes.origin.pull()
                self.last_pull_time = time.time()
                print("Success! Changes were pulled.")
            except Exception as e:
                print(f"Failed to pull changes: {e}")

            self.initiate_restart()


if __name__ == "__main__":
    command = ["python", "-m", "bot.main"]
    # command = "uvicorn bot.main:wsgi_app --host 0.0.0.0 --port 5000 --workers 1 --log-level info".split()
    target_file = "bot/resources/dumps/head-commit.json"

    # Set up the watchdog observer
    event_handler = RestartHandler(command=command, target_file=target_file)
    event_handler.start_process()
    observer = Observer()
    observer.schedule(event_handler, path=os.path.dirname(target_file), recursive=False)

    try:
        observer.start()
        print(f"Watching {target_file} for changes. Press Ctrl+C to exit.")
        while True:
            event_handler.check_full_restart_signal()
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down observer and terminating processes...")
        observer.stop()
        event_handler.terminate_process()

    observer.join()
    print("Script terminated.")
