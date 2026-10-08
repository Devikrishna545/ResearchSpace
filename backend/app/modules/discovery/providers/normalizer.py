from app.modules.papers.schemas.paper import Paper,RawPaperRecord
from app.shared.identifiers import arxiv_id_from_doi,canonical_arxiv_id
from app.shared.text import clean_metadata_text

class Normalizer:
    def normalize(self,records:list[RawPaperRecord])->list[Paper]:
        papers=[]
        for record in records:
            title=clean_metadata_text(record.title)
            if not title:
                continue
            inferred=arxiv_id_from_doi(record.doi)
            explicit=canonical_arxiv_id(record.arxiv_id)
            if inferred and explicit and inferred!=explicit:
                raise ValueError("Paper metadata has conflicting arXiv identifiers for its DOI")
            data=record.model_dump(exclude={'url'})
            data['title']=title
            data['abstract']=clean_metadata_text(record.abstract)
            if inferred and not explicit:
                data['arxiv_id']=inferred
            papers.append(Paper(**data))
        return papers
