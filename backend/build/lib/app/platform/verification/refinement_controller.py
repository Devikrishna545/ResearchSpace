from app.platform.verification.convergence import Convergence
from app.platform.verification.policies import LoopPolicies
class RefinementController:
    def __init__(self,policies:LoopPolicies,convergence:Convergence|None=None): self.policies=policies; self.convergence=convergence or Convergence()
    def prepare_verdict(self,verdict,draft=None,evidence=None,matches=None,require_joint_evidence=False): return self.policies.prepare_verdict(verdict,draft,evidence,matches,require_joint_evidence)
    def decide(self,verdict,iteration:int,elapsed_ms:int,history,draft=None,evidence=None,require_joint_evidence=False): return self.policies.decide(verdict,iteration,elapsed_ms,history,self.convergence,draft,evidence,require_joint_evidence)
