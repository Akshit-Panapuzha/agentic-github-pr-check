import hashlib
from dataclasses import dataclass, field


@dataclass
class Finding:
    filename: str
    line_number: int
    agent: str        # "quality" | "security"
    severity: str     # "critical" | "high" | "medium" | "low"
    title: str
    explanation: str
    suggestion: str
    confidence: float = 0.0
    id: str = field(default="")

    def __post_init__(self):
        if not self.id:
            raw = f"{self.filename}{self.line_number}{self.agent}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]
