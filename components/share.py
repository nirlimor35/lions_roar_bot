class IncidentHandlerLog:
    NEW = "\033[93mNew Incident\033[0m"
    EXISTING = "\033[93mExisting Incident\033[0m"
    OPENED = "\033[91;1mOpened Incident\033[0m"
    NOT_OPENED = "\033[93;2mNot Opened\033[0m"
    ENDED = "\033[92;1mEnded Incident\033[0m"
    MANUAL = "\033[92;1mManual Close\033[0m"
    ENDED_CANDIDATE = "\033[92;2mEnded Incident Candidate\033[0m"