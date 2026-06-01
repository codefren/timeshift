import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import desc, asc

from dependencies import SessionDep, get_current_user, LocationFiltersDep, PaginationDep
from SQLModels import (
    Locations, LocationList
)
from .models import LocationCreate, LocationUpdate

router = APIRouter(
    prefix="/api/locations",
    tags=["Locations"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


@router.post("/", response_model=Locations)
def create_location(db: SessionDep,
                    location: LocationCreate,
                    ):
    log = logging.getLogger(__name__)
    log.debug(f"Creating location {location.LocationName}")
    location = location.create(db)
    log.debug(f"Location {location.LocationName} created")
    return location

@router.put("/{loc_id}/", response_model=Locations)
def update_location(db: SessionDep,
                    loc_id: int,
                    loc: LocationUpdate):
    loc.LocationID = loc_id
    log = logging.getLogger(__name__)
    log.debug(f"Updating location {loc_id}")
    location = loc.update(db)
    log.debug(f"Location {loc_id} updated")
    return location

@router.delete("/{loc_id}/", response_model=Locations)
def delete_location(db: SessionDep,
                    loc_id: int,
                    ):
    log = logging.getLogger(__name__)
    log.debug(f"Deleting location {loc_id}")
    location = Locations.get(db, loc_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    location.deactivate(db)
    log.debug(f"Location {loc_id} deactivated")
    return location

@router.get("/{loc_id}/", response_model=Locations)
def get_location_by_id(db: SessionDep,
                    loc_id: int,
                    ):
    log = logging.getLogger(__name__)
    log.debug(f"Getting location by id {loc_id}")
    model = Locations.get(db, loc_id)
    if not model:
        raise HTTPException(status_code=404, detail="Location not found")
    log.debug(f"Location by id {loc_id} obtained")
    return model

@router.get("/", response_model=LocationList)
def list_locations(db: SessionDep,
                   params: PaginationDep,
                   filters: LocationFiltersDep,
                   ):
    log = logging.getLogger(__name__)
    log.debug(f"Listing locations")
    params.order = desc if params.order == "desc" else asc
    return Locations.list(db, params, filters)
