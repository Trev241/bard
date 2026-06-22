import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import git
import psutil
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot import config


REBOOT_GRACE_PERIOD = 10
MODIFICATION_COOLDOWN_PERIOD = 5
YTDLP_UPDATE_COMMAND = [
    "pip",
    "install",
    "-U",
    "--pre",
    "yt-dlp[default]",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class RestartHandler(FileSystemEventHandler):
    def __init__(self, command, target_file):
        self.command = command
        self.target_file = target_file
        self.process = None
        self.timer = None
        self.repo = git.Repo(config.PROJECT_ROOT)
        self.last_pull_time = 0

    def start_process(self):
        self.timer = None
        if self.process and self.is_process_running():
            logger.info("Process is already running; terminating it first.")
            self.terminate_process()

        logger.info("Starting process: %s", " ".join(self.command))
        self.process = subprocess.Popen(self.command, cwd=config.PROJECT_ROOT)
        logger.info("Process started with PID: %s", self.process.pid)

    def is_process_running(self):
        return self.process is not None and self.process.poll() is None

    def restart_process(self):
        logger.info("Restarting process.")
        self.terminate_process()
        self.refresh_ytdlp()
        time.sleep(1)
        self.start_process()

    def refresh_ytdlp(self):
        if not config.WATCHER_UPDATE_YTDLP_ON_RESTART:
            logger.info("Skipping yt-dlp refresh; disabled by configuration.")
            return

        logger.info("Refreshing yt-dlp before restart.")
        try:
            result = subprocess.run(
                YTDLP_UPDATE_COMMAND,
                cwd=config.PROJECT_ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=config.WATCHER_YTDLP_UPDATE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "yt-dlp refresh timed out after %s seconds; continuing startup.",
                config.WATCHER_YTDLP_UPDATE_TIMEOUT,
                exc_info=True,
            )
            return
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "yt-dlp refresh failed; continuing startup. Output:\n%s",
                exc.stdout,
            )
            return

        output = result.stdout.strip()
        if output:
            logger.info("yt-dlp refresh output:\n%s", output)

    def initiate_restart(self):
        if self.timer is not None:
            return

        config.RESTART_SIGNAL_FILE.write_text("restart")
        logger.info("Rebooting in %s seconds.", REBOOT_GRACE_PERIOD)
        self.timer = threading.Timer(REBOOT_GRACE_PERIOD, self.restart_process)
        self.timer.start()

    def check_full_restart_signal(self):
        if not config.RESTART_SIGNAL_TRIGGER_FILE.exists():
            return

        logger.info("Detected restart trigger file; initiating restart.")
        try:
            config.RESTART_SIGNAL_TRIGGER_FILE.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to remove restart trigger file.", exc_info=True)

        self.initiate_restart()

    def terminate_process(self):
        if not self.process:
            return

        try:
            proc = psutil.Process(self.process.pid)
            children = proc.children(recursive=True)

            logger.info("Terminating process with PID: %s", self.process.pid)
            for child in children:
                logger.info("Terminating child process with PID: %s", child.pid)
                child.terminate()

            proc.terminate()
            _, alive = psutil.wait_procs([proc, *children], timeout=5)
            for remaining in alive:
                logger.warning("Killing unresponsive process with PID: %s", remaining.pid)
                remaining.kill()
        except psutil.NoSuchProcess:
            logger.info("Process no longer exists.")
        except Exception:
            logger.warning("Error terminating process tree.", exc_info=True)

        self.process = None

    def on_modified(self, event):
        try:
            changed_path = config.PROJECT_ROOT / event.src_path
            if changed_path.resolve() != self.target_file.resolve():
                return
        except FileNotFoundError:
            return

        current_time = time.time()
        if current_time - self.last_pull_time < MODIFICATION_COOLDOWN_PERIOD:
            logger.info("Ignoring modification due to recent git pull cooldown.")
            return

        logger.info("Detected change in %s; pulling changes.", self.target_file)
        try:
            self.repo.remotes.origin.pull()
            self.last_pull_time = time.time()
            logger.info("Changes pulled successfully.")
        except Exception:
            logger.warning("Failed to pull changes.", exc_info=True)

        self.initiate_restart()


def main():
    command = ["python", "-m", "bot.main"]
    target_file = config.HEAD_COMMIT_DUMP

    event_handler = RestartHandler(command=command, target_file=target_file)
    event_handler.start_process()

    observer = Observer()
    observer.schedule(
        event_handler,
        path=str(target_file.parent),
        recursive=False,
    )

    try:
        observer.start()
        logger.info("Watching %s. Press Ctrl+C to exit.", target_file)
        while True:
            event_handler.check_full_restart_signal()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down observer and process.")
        observer.stop()
        event_handler.terminate_process()

    observer.join()
    logger.info("Watcher stopped.")


if __name__ == "__main__":
    main()
