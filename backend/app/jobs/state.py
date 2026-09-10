from app.models.job import JobStatus


class InvalidTransition(ValueError):
    """Raised when a job attempts an unsupported lifecycle transition."""


VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED},
    JobStatus.RUNNING: {
        JobStatus.SUCCEEDED,
        JobStatus.RETRYING,
        JobStatus.FAILED,
        JobStatus.DEAD_LETTER,
    },
    JobStatus.RETRYING: {JobStatus.RUNNING, JobStatus.DEAD_LETTER},
    JobStatus.FAILED: {JobStatus.QUEUED},
    JobStatus.DEAD_LETTER: {JobStatus.QUEUED},
    JobStatus.SUCCEEDED: set(),
}


def transition(current: JobStatus, target: JobStatus) -> JobStatus:
    if target not in VALID_TRANSITIONS[current]:
        raise InvalidTransition(f"Invalid job transition: {current} -> {target}")
    return target


def validate_progress(progress: int) -> int:
    if not 0 <= progress <= 100:
        raise ValueError("Job progress must be between 0 and 100")
    return progress

