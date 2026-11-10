from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Source:
    path: Path
    ref: str | None = None


@dataclass(frozen=True)
class Config:
    destination: Path
    branch: str
    name: str
    email: str
    work_emails: frozenset[str]
    sources: tuple[Source, ...]


def load_config(path: Path) -> Config:
    path = path.resolve()
    with path.open("rb") as stream:
        data = tomllib.load(stream)

    def resolve(value: str) -> Path:
        if not isinstance(value, str) or not value.strip() or "REPLACE_WITH" in value:
            raise ValueError("Replace all configuration path placeholders before running")
        return (path.parent / Path(value).expanduser()).resolve()

    target = data["destination"]
    name, email = target["name"], target["email"]
    for label, value in (("name", name), ("email", email)):
        if not isinstance(value, str) or not value.strip() or "REPLACE_WITH" in value or any(c in value for c in "\r\n\x00<>"):
            raise ValueError(f"Invalid destination {label}")
    emails = data["work_emails"]
    if not isinstance(emails, list) or not emails or any(not isinstance(e, str) or not e.strip() for e in emails):
        raise ValueError("work_emails must be a nonempty list of exact author emails")
    if any("REPLACE_WITH" in email for email in emails):
        raise ValueError("Replace the work_emails placeholder before running")
    destination = resolve(target["path"])
    sources = tuple(Source(resolve(s["path"]), s.get("ref")) for s in data["sources"])
    if not sources:
        raise ValueError("At least one source is required")
    if any(s.path == destination for s in sources):
        raise ValueError("A source cannot be the destination")
    return Config(destination, target.get("branch", "main"), name, email, frozenset(emails), sources)
