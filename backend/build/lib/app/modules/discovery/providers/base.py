from abc import ABC,abstractmethod
from app.shared.schemas.common import SourceHealth
from app.modules.papers.schemas.paper import PaperIdentifier,RawPaperRecord
from app.modules.discovery.schemas import SearchQuery
class SourceAdapter(ABC):
    name:str
    @abstractmethod
    async def search(self,query:SearchQuery)->list[RawPaperRecord]: ...
    async def fetch_by_id(self,identifier:PaperIdentifier)->RawPaperRecord|None: return None
    async def resolve_fulltext(self,record:RawPaperRecord)->str|None: return record.pdf_url
    async def health_check(self)->SourceHealth: return SourceHealth(source=self.name)
