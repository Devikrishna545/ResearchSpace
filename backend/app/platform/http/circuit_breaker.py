from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
class CircuitState(StrEnum): CLOSED='closed'; OPEN='open'; HALF_OPEN='half_open'
@dataclass
class CircuitBreaker:
    failure_threshold:int=3; reset_timeout_s:float=30.0; state:CircuitState=CircuitState.CLOSED; failures:int=0; opened_at:float|None=None
    def allow(self)->bool:
        if self.state!=CircuitState.OPEN: return True
        if self.opened_at and monotonic()-self.opened_at>=self.reset_timeout_s: self.state=CircuitState.HALF_OPEN; return True
        return False
    def record_success(self): self.failures=0; self.state=CircuitState.CLOSED; self.opened_at=None
    def record_failure(self):
        self.failures+=1
        if self.failures>=self.failure_threshold: self.state=CircuitState.OPEN; self.opened_at=monotonic()
