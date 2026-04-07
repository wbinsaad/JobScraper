from fastapi import APIRouter, HTTPException, Request

from aggregator_service.api.state import get_con_factory

router = APIRouter()


@router.get("/health")
def health(request: Request):
    con_factory = get_con_factory(request)
    con = con_factory()
    try:
        con.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")
    finally:
        con.close()
