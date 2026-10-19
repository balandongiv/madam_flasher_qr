"""What the audience display window is currently showing (server-side, shared by all windows)."""
from __future__ import annotations

import threading
from typing import Any

from app.data import Student


class DisplayState:
    """Current display content, plus the next student waiting to be shown.

    Every lookup is staged as `pending`. It reaches the display only on confirm() (shortcut N), or as the
    default image via show_default() (shortcut B). What is on screen stays until replaced or cleared.
    """

    def __init__(self, show_name_caption: bool):
        self.show_name_caption = show_name_caption
        self._lock = threading.Lock()
        self._version = 0
        self._student: Student | None = None
        self._image_url: str | None = None
        self._pending: tuple[Student, str] | None = None

    def _show(self, student: Student, image_url: str) -> None:
        self._student = student
        self._image_url = image_url
        self._version += 1

    def stage(self, student: Student, image_url: str | None = None) -> None:
        """Hold a student as the next image until confirm() / show_default() (or until replaced / cleared)."""
        with self._lock:
            self._pending = (student, image_url or f"/api/image/{student.metric_no}")
            self._version += 1

    def confirm(self) -> bool:
        """Put the pending student on the display. False if nothing was pending."""
        with self._lock:
            if self._pending is None:
                return False
            student, image_url = self._pending
            self._pending = None
            self._show(student, image_url)
            return True

    def show_default(self, default_url: str) -> bool:
        """Show the default image instead: for the pending student if any, else in place of the current image."""
        with self._lock:
            if self._pending is not None:
                student = self._pending[0]
                self._pending = None
            elif self._student is not None:
                student = self._student
            else:
                return False
            self._show(student, default_url)
            return True

    def clear(self) -> None:
        with self._lock:
            if self._student is not None or self._pending is not None:
                self._student = None
                self._image_url = None
                self._pending = None
                self._version += 1

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            p = self._pending
            pending = None if p is None else {"metric_no": p[0].metric_no, "image_url": p[1],
                                              "student": p[0].to_dict()}
            s = self._student
            if s is None:
                return {"version": self._version, "mode": "idle", "pending": pending}
            return {
                "version": self._version,
                "mode": "image",
                "metric_no": s.metric_no,
                "image_url": self._image_url,
                "caption": f"{s.name}" if self.show_name_caption else None,
                "student": s.to_dict(),
                "pending": pending,
            }
