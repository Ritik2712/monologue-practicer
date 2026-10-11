"""Errors the pipeline raises on purpose. Their messages are written for the user and never
contain file paths, transcripts or other details of the recording."""


class PipelineError(Exception):
    """A failure with a stable code and a message that is safe to show.

    `retryable` says whether running the very same job again could succeed. A file that is
    not audio will fail every time; a missing speech model will not, once it is installed.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class JobCancelled(Exception):
    """Raised at a safe point after the user asked for the job to be cancelled."""


class WorkerStopping(Exception):
    """Raised at a safe point when the worker is shutting down; the job goes back in the queue."""
