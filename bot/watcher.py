import os
import subprocess
import time
import git

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class RestartHandler(FileSystemEventHandler):
    def __init__(self, command, target_file):
        self.command = command
        self.target_file = target_file
        self.process = None
        self.last_modified = 0
        self.repo = git.Repo()
        self.start_process()

    def start_process(self):
        """Start the process."""
        self.process = subprocess.Popen(self.command, shell=True)

    def restart_process(self):
        """Restart the process."""
        if self.process:
            self.process.terminate()
            self.process.wait()

        self.start_process()

    def on_modified(self, event):
        """Handle file modification events by restarting the app if the target file is modified."""
        if event.src_path == os.path.relpath(self.target_file):
            current_time = time.time()

            if current_time - self.last_modified > 1:  # 1-second threshold
                print(
                    f"Detected modification in {event.src_path}, restarting Flask app."
                )
                print("Pulling changes...")
                self.repo.remotes.origin.pull()
                print("Success! Changes were pulled.")
                self.restart_process()
                self.last_modified = current_time


if __name__ == "__main__":
    command = "python -m bot.main"
    target_file = "bot/resources/dumps/head-commit.json"

    # Set up the watchdog observer
    event_handler = RestartHandler(command=command, target_file=target_file)
    observer = Observer()
    # Watch the directory containing the target file
    observer.schedule(event_handler, path=os.path.dirname(target_file), recursive=False)

    try:
        observer.start()
        print(f"Watching {target_file} for changes. Press Ctrl+C to exit.")
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
