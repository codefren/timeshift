import logging
from typing import Optional, Self

from pydantic import BaseModel, Field
from sqlmodel import Session

from SQLModels import Locations


class LocationCreate(BaseModel):
    LocationName: str = Field(max_length=50)
    Address: str = Field(max_length=50)
    ZipCode: str = Field(max_length=10)
    City: str = Field(max_length=50)
    State: str = Field(max_length=50)
    Country: str = Field(max_length=50)
    Lat: Optional[float] | None = Field(None)
    Lon: Optional[float] | None = Field(None)

    def generate_latlon(self) -> None:
        log = logging.getLogger(__name__)
        log.debug(f"Generating latlon for {self.Address}, {self.ZipCode}, {self.City}, {self.State}, {self.Country}")
        latlong = Locations.validate_address_google(self.Address, self.ZipCode, self.City, self.State, self.Country)
        log.debug(f"Latlon generated: {latlong}")
        if not latlong['is_valid']:
            log.debug(f"Invalid address {self.Address}, {self.ZipCode}, {self.City}, {self.State}, {self.Country}")
            raise ValueError("Invalid address")
        self.Lat = latlong['latitude']
        self.Lon = latlong['longitude']
        self.Address = latlong['formatted_address']

    def create_formatted_address(self) -> str:
        return f"{self.Address.strip()}, {self.ZipCode.strip()} {self.City.strip()}, {self.State.strip()}, {self.Country.strip()}"

    def check_by_address(self, db: Session) -> Self:
        location = Locations.get_by_address(db, self.create_formatted_address(), active=False)
        if location:
            self.Lat = location.Lat
            self.Lon = location.Long
            self.Address = location.Address
            self.ZipCode = location.ZipCode
            self.City = location.City
            self.State = location.State
            self.Country = location.Country
        return self

    def create(self, db: Session) -> Locations:
        if Locations.get_by_name(db, self.LocationName):
            raise ValueError("Location already exists")
        self.check_by_address(db)
        if not self.Lat or not self.Lon:
            self.generate_latlon()
        location = Locations(LocationName=self.LocationName, Address=self.Address, ZipCode=self.ZipCode,
                             City=self.City, State=self.State, Country=self.Country,
                             Lat=self.Lat, Long=self.Lon)
        return location.create(db)


class LocationUpdate(BaseModel):
    LocationName: Optional[str] = Field(None, max_length=50)
    Address: Optional[str] = Field(None, max_length=50)
    ZipCode: Optional[str] = Field(None, max_length=10)
    City: Optional[str] = Field(None, max_length=50)
    State: Optional[str] = Field(None, max_length=50)
    Country: Optional[str] = Field(None, max_length=50)
    Lat: Optional[float] | None = Field(None)
    Lon: Optional[float] | None = Field(None)
    LocationID: Optional[int] = Field(None, description="Location ID", ge=1)

    def update(self, db: Session) -> Locations:
        if not self.LocationID and not self.LocationName:
            raise ValueError("Location ID or Name required")
        if not self.LocationID:
            loc = Locations.get_by_name(db, self.LocationName)
            self.LocationID = self.LocationID.LocationID if loc else None
            if not self.LocationID:
                raise ValueError("Location not found")
        else:
            loc = Locations.get(db, self.LocationID)
            if not loc:
                raise ValueError("Location not found")

        return loc.update(db, **self.model_dump(mode='python'))
