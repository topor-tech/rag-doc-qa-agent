from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4


@dataclass
class Message:
    role: str
    content: str


@dataclass
class Session:
    id: str
    messages: list[Message] = field(default_factory=list)


class SessionStore:
    def __init__(self) -> None:
        self._items: dict[str, Session] = {}
        self._locks: dict[str, Lock] = {}
        self._guard = Lock()

    def create(self) -> Session:
        session = Session(id=str(uuid4()))
        with self._guard:
            self._items[session.id] = session
            self._locks[session.id] = Lock()
        return Session(id=session.id, messages=[])

    def snapshot(self, session_id: str) -> Session | None:
        session, lock = self._lookup(session_id)
        if session is None or lock is None:
            return None
        with lock:
            return Session(id=session.id, messages=list(session.messages))

    def add_message(self, session_id: str, role: str, content: str) -> Session | None:
        session, lock = self._lookup(session_id)
        if session is None or lock is None:
            return None
        with lock:
            session.messages.append(Message(role=role, content=content))
            return Session(id=session.id, messages=list(session.messages))

    def _lookup(self, session_id: str) -> tuple[Session | None, Lock | None]:
        with self._guard:
            return self._items.get(session_id), self._locks.get(session_id)
