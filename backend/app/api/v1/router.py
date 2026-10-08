from fastapi import APIRouter, Depends
from app.modules.auth import api as auth
from app.modules.chat import api as chat
from app.modules.compare import api as compare
from app.modules.compare import grounded_api as grounded
from app.api.v1 import health
from app.modules.sharing import api as linkedin
from app.modules.notes import api as notes
from app.modules.papers import api as papers
from app.modules.discovery import api as search
from app.modules.spaces import api as spaces
from app.modules.chat import verification_api as verification
from app.core.auth import current_user
from app.core.ownership import require_owned_resources
api_router=APIRouter()
api_router.include_router(auth.router,prefix='/auth',tags=['auth'])
api_router.include_router(linkedin.router,prefix='/linkedin',tags=['linkedin'])
api_router.include_router(health.router,prefix='/admin',tags=['admin'],dependencies=[Depends(current_user)])
api_router.include_router(spaces.router,prefix='/spaces',tags=['spaces'],dependencies=[Depends(require_owned_resources)])
api_router.include_router(search.router,tags=['search'],dependencies=[Depends(require_owned_resources)])
api_router.include_router(papers.router,tags=['papers'],dependencies=[Depends(require_owned_resources)])
api_router.include_router(chat.router,tags=['chat'],dependencies=[Depends(require_owned_resources)])
api_router.include_router(compare.router,tags=['compare'],dependencies=[Depends(require_owned_resources)])
api_router.include_router(grounded.router,tags=['grounded-compare'],dependencies=[Depends(require_owned_resources)])
api_router.include_router(notes.router,tags=['notes'],dependencies=[Depends(require_owned_resources)])
api_router.include_router(verification.router,tags=['verification'],dependencies=[Depends(require_owned_resources)])
