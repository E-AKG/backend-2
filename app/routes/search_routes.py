from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import List, Optional
from ..db import get_db
from ..models.user import User
from ..models.property import Property
from ..models.unit import Unit
from ..models.tenant import Tenant
from ..models.lease import Lease
from ..models.billrun import Charge, ChargeStatus
from ..utils.deps import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/api/search", tags=["Search"])


class SearchResult(BaseModel):
    id: str
    type: str  # "property", "unit", "tenant", "charge", "lease"
    title: str
    subtitle: Optional[str] = None
    url: str
    metadata: Optional[dict] = None

    class Config:
        from_attributes = True


@router.get("/spotlight", response_model=List[SearchResult])
def spotlight_search(
    q: str = Query(..., min_length=1, description="Suchbegriff"),
    client_id: Optional[str] = Query(None, description="Filter nach Mandant"),
    fiscal_year_id: Optional[str] = Query(None, description="Filter nach Geschäftsjahr"),
    limit: int = Query(20, ge=1, le=50, description="Maximale Anzahl Ergebnisse"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Globale Spotlight-Suche (CMD+K)
    Durchsucht Objekte, Einheiten, Mieter, Offene Posten, Verträge
    """
    results = []
    search_term = f"%{q.lower()}%"
    
    # Filter für Mandant
    filters = []
    if client_id:
        # TODO: Add client_id filters after migration
        # filters.append(Property.client_id == client_id)
        # filters.append(Unit.client_id == client_id)
        # filters.append(Tenant.client_id == client_id)
        # filters.append(Lease.client_id == client_id)
        pass
    
    # 1. Objekte suchen
    properties_query = db.query(Property).filter(
        Property.owner_id == current_user.id,
        or_(
            func.lower(Property.name).like(search_term),
            func.lower(Property.address).like(search_term)
        )
    )
    # TODO: Add client_id filter after migration: if client_id: properties_query = properties_query.filter(Property.client_id == client_id)
    
    properties = properties_query.limit(5).all()
    for prop in properties:
        results.append(SearchResult(
            id=prop.id,
            type="property",
            title=prop.name,
            subtitle=prop.address,
            url=f"/verwaltung/{prop.id}",
            metadata={"address": prop.address}
        ))
    
    # 2. Einheiten suchen
    units_query = db.query(Unit).join(Property).filter(
        Unit.owner_id == current_user.id,
        or_(
            func.lower(Unit.unit_label).like(search_term),
            func.lower(Property.name).like(search_term)
        )
    )
    # TODO: Add client_id filter after migration
    # if client_id:
    #     units_query = units_query.filter(Unit.client_id == client_id)
    
    units = units_query.limit(5).all()
    for unit in units:
        results.append(SearchResult(
            id=unit.id,
            type="unit",
            title=f"{unit.property.name} - {unit.unit_label}",
            subtitle=f"{unit.property.address}",
            url=f"/verwaltung/{unit.property_id}?unit={unit.id}",
            metadata={"property": unit.property.name, "label": unit.unit_label}
        ))
    
    # 3. Mieter suchen
    tenants_query = db.query(Tenant).filter(
        Tenant.owner_id == current_user.id,
        or_(
            func.lower(Tenant.first_name).like(search_term),
            func.lower(Tenant.last_name).like(search_term),
            func.lower(Tenant.email).like(search_term),
            func.lower(Tenant.phone).like(search_term)
        )
    )
    # TODO: Add client_id filter after migration
    # if client_id:
    #     tenants_query = tenants_query.filter(Tenant.client_id == client_id)
    
    tenants = tenants_query.limit(5).all()
    for tenant in tenants:
        results.append(SearchResult(
            id=tenant.id,
            type="tenant",
            title=f"{tenant.first_name} {tenant.last_name}",
            subtitle=tenant.email or tenant.phone or "Keine Kontaktdaten",
            url=f"/personen/{tenant.id}",
            metadata={"email": tenant.email, "phone": tenant.phone}
        ))
    
    # 4. Offene Posten suchen
    charges_query = db.query(Charge).join(Lease).join(Tenant).join(Unit).join(Property).filter(
        Property.owner_id == current_user.id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE]),
        or_(
            func.lower(Tenant.first_name).like(search_term),
            func.lower(Tenant.last_name).like(search_term),
            func.lower(Property.name).like(search_term),
            func.lower(Unit.unit_label).like(search_term)
        )
    )
    # TODO: Add client_id filter after migration: if client_id: charges_query = charges_query.filter(Property.client_id == client_id)
    
    charges = charges_query.limit(5).all()
    for charge in charges:
        tenant = charge.lease.tenant
        unit = charge.lease.unit
        property_obj = unit.property
        results.append(SearchResult(
            id=charge.id,
            type="charge",
            title=f"Offene Posten: {tenant.first_name} {tenant.last_name}",
            subtitle=f"{property_obj.name} - {unit.unit_label} | {float(charge.amount - charge.paid_amount):.2f} €",
            url=f"/finanzen?charge={charge.id}",
            metadata={
                "amount": float(charge.amount),
                "paid": float(charge.paid_amount),
                "due_date": charge.due_date.isoformat() if charge.due_date else None
            }
        ))
    
    # 5. Verträge suchen
    leases_query = db.query(Lease).join(Tenant).join(Unit).join(Property).filter(
        Property.owner_id == current_user.id,
        or_(
            func.lower(Tenant.first_name).like(search_term),
            func.lower(Tenant.last_name).like(search_term),
            func.lower(Property.name).like(search_term),
            func.lower(Unit.unit_label).like(search_term)
        )
    )
    # TODO: Add client_id filter after migration
    # if client_id:
    #     leases_query = leases_query.filter(Lease.client_id == client_id)
    
    leases = leases_query.limit(5).all()
    for lease in leases:
        tenant = lease.tenant
        unit = lease.unit
        property_obj = unit.property
        results.append(SearchResult(
            id=lease.id,
            type="lease",
            title=f"Vertrag: {tenant.first_name} {tenant.last_name}",
            subtitle=f"{property_obj.name} - {unit.unit_label}",
            url=f"/vertraege/{lease.id}",
            metadata={
                "start_date": lease.start_date.isoformat() if lease.start_date else None,
                "status": lease.status.value
            }
        ))
    
    # Sortiere nach Relevanz (einfache Heuristik: kürzere Titel = relevanter)
    results.sort(key=lambda x: len(x.title))
    
    return results[:limit]


@router.get("/quick-stats")
def quick_stats(
    client_id: Optional[str] = Query(None),
    fiscal_year_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Schnelle Statistiken für Dashboard-KPIs
    """
    from ..models.client import Client
    from ..models.fiscal_year import FiscalYear
    
    # Basis-Filter - nur owner_id, client_id Filter nur wenn Spalte existiert
    # Anzahl Objekte
    properties_query = db.query(Property).filter(Property.owner_id == current_user.id)
    # TODO: Add client_id filter after migration: if client_id: properties_query = properties_query.filter(Property.client_id == client_id)
    properties_count = properties_query.count()
    
    # Anzahl Einheiten
    units_query = db.query(Unit).filter(Unit.owner_id == current_user.id)
    # TODO: Add client_id filter after migration
    # if client_id:
    #     units_query = units_query.filter(Unit.client_id == client_id)
    units_count = units_query.count()
    
    # Anzahl Mieter
    tenants_query = db.query(Tenant).filter(Tenant.owner_id == current_user.id)
    # TODO: Add client_id filter after migration
    # if client_id:
    #     tenants_query = tenants_query.filter(Tenant.client_id == client_id)
    tenants_count = tenants_query.count()
    
    # Anzahl aktive Verträge
    from ..models.lease import LeaseStatus
    leases_query = db.query(Lease).filter(
        Lease.owner_id == current_user.id,
        Lease.status == LeaseStatus.ACTIVE
    )
    # TODO: Add client_id filter after migration
    # if client_id:
    #     leases_query = leases_query.filter(Lease.client_id == client_id)
    active_leases_count = leases_query.count()
    
    # Leerstand
    from ..models.unit import UnitStatus
    vacant_query = db.query(Unit).filter(
        Unit.owner_id == current_user.id,
        Unit.status == UnitStatus.VACANT
    )
    if client_id:
        try:
            vacant_query = vacant_query.filter(Unit.client_id == client_id)
        except:
            pass
    vacant_units = vacant_query.count()
    vacancy_rate = int((vacant_units / units_count * 100) if units_count > 0 else 0)
    
    # Offene Posten (Summe)
    open_charges_query = db.query(Charge).join(Lease).join(Unit).join(Property).filter(
        Property.owner_id == current_user.id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE])
    )
    # TODO: Add client_id filter after migration: if client_id: open_charges_query = open_charges_query.filter(Property.client_id == client_id)
    
    open_charges = open_charges_query.all()
    total_open_amount = sum(float(c.amount - c.paid_amount) for c in open_charges)
    open_charges_count = len(open_charges)
    
    return {
        "properties": properties_count,
        "units": units_count,
        "tenants": tenants_count,
        "active_leases": active_leases_count,
        "vacancy": {
            "count": vacant_units,
            "rate": vacancy_rate
        },
        "open_charges": {
            "count": open_charges_count,
            "total_amount": total_open_amount
        }
    }

