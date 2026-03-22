from fastapi import Depends, FastAPI
from shared.schemas.search import SearchRequest, SearchResult

from search.strategies.example_strategy import ExampleStrategy
from search.strategies.search_strategy import SearchStrategy

app = FastAPI()


def get_search_strategy() -> SearchStrategy:
    return ExampleStrategy()


@app.post("/search", response_model=SearchResult)
async def search(
    request: SearchRequest,
    strategy: SearchStrategy = Depends(get_search_strategy),
) -> SearchResult:
    result = await strategy.search(request.query)
    return SearchResult(result=result)
