from fastapi import FastAPI
from shared.schemas.search import SearchRequest, SearchResult

app = FastAPI()

@app.post("/search", response_model=SearchResult)
async def search(request: SearchRequest) -> SearchResult:
    # TODO: Implement search logic (use strategy pattern for different search backends)
    return SearchResult(result=request.query)
