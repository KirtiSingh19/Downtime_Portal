import os
import sys
import time
import logging
from pathlib import Path

# Run as "python users/hrms_watcher.py", sys.path[0] is users/, not the project
# root, so "import users" would fail. Django also has to be configured before
# any users.* import, because those pull in the model layer.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "UploadData.settings")

import django

django.setup()

from django.conf import settings
# PollingObserver, not the default Observer: the default uses inotify, and
# inotify events do not cross a Docker Desktop bind mount from a Windows
# host, so arriving files were never noticed. Polling stats the directory
# instead, which works on any filesystem.
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

from users.tasks import process_hrms_dump


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


class HRMSFileHandler(FileSystemEventHandler):

    ALLOWED_EXTENSIONS = {
        ".csv",
        ".xlsx",
        ".xls",
    }

    def on_created(self, event):

        if event.is_directory:
            return

        self.handle_path(Path(event.src_path))

    def on_moved(self, event):
        # Transfers commonly land as a temp name and are then renamed into
        # place, which is a move, not a create. Without this the real arrival
        # would go unnoticed.
        if event.is_directory:
            return
        self.handle_path(Path(event.dest_path))

    def handle_path(self, file_path):
        if file_path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
            return
        if file_path.stem.endswith("_cleaned"):
            return

        logger.info("New HRMS file detected: %s", file_path)
        self.wait_until_file_ready(file_path)
        self.queue_processing(file_path)

    @staticmethod
    def queue_processing(file_path):
        """Queue the work on the existing Celery worker.

        Deliberately not called ``dispatch``: that name belongs to
        FileSystemEventHandler's event router, and overriding it would send
        every raw event here instead of to on_created/on_moved.

        The task carries the lock, so several events for one arriving file
        collapse into a single run.
        """
        try:
            process_hrms_dump.delay()
            logger.info("Queued HRMS processing for %s", file_path)

        except Exception as e:
            logger.exception(
                "Could not queue HRMS processing for %s: %s", file_path, e
            )

    @staticmethod
    def wait_until_file_ready(
        file_path,
        wait_seconds=2,
        max_attempts=30
    ):
        """
        Wait until the file size stops changing.
        This prevents reading a partially copied Excel/CSV file.
        """

        previous_size = -1

        for _ in range(max_attempts):

            if not file_path.exists():
                return

            current_size = file_path.stat().st_size

            if current_size == previous_size:
                return

            previous_size = current_size

            time.sleep(wait_seconds)


def start_hrms_watcher():

    hrms_dump_dir = Path(settings.MEDIA_ROOT) / "hrms_dump"

    hrms_dump_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    event_handler = HRMSFileHandler()

    observer = Observer()

    observer.schedule(
        event_handler,
        str(hrms_dump_dir),
        recursive=False
    )

    observer.start()

    logger.info(
        "HRMS watcher started: %s",
        hrms_dump_dir
    )

    # A file that arrived while this process was down would otherwise sit
    # unnoticed until the next one appeared, so sweep once on startup. The
    # task's lock keeps this from colliding with a live event.
    waiting = [
        path for path in sorted(hrms_dump_dir.iterdir())
        if path.is_file()
        and path.suffix.lower() in HRMSFileHandler.ALLOWED_EXTENSIONS
        and not path.stem.endswith("_cleaned")
    ]
    if waiting:
        logger.info(
            "Found %s HRMS file(s) already waiting: %s",
            len(waiting), ", ".join(p.name for p in waiting),
        )
        HRMSFileHandler.queue_processing(waiting[-1])

    try:

        while True:
            time.sleep(5)

    except KeyboardInterrupt:

        observer.stop()

    observer.join()


if __name__ == "__main__":

    start_hrms_watcher()