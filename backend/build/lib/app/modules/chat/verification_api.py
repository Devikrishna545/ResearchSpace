from fastapi import APIRouter
from app.platform.verification.trail_store import trail
router=APIRouter()
@router.get('/turns/{turn_id}/verification')
async def verification_trail(turn_id:str):
    traces=await trail.get(turn_id)
    return {'turn_id':turn_id,'iterations':[t.model_dump(mode='json') for t in traces]}
