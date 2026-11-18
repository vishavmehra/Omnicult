from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import CurrentUser
from app.schemas.common import CountryCode
from app.schemas.country_packs import CountryPack
from app.services import country_pack

router = APIRouter(tags=["country-packs"])


@router.get("/country-packs/{country_code}", response_model=CountryPack)
async def get_country_pack(
    country_code: Annotated[CountryCode, Path(description="ISO 3166-1 alpha-2 code. Only IN exists.")], user: CurrentUser
) -> CountryPack:
    """The versioned India pack: regions, languages and scripts, calendar sources, ad codes, data sources with dates and
    licences, and known gaps. It describes and links the reference data; it does not copy it."""
    return await country_pack.get_country_pack(country_code)
