"""A contract extraction template for docling-graph.

Deliberately mirrors the facet set of SECTION-SUMMARY-ARCHITECTURE.md section 6.3
so the two designs are compared on the same targets: parties, term/expiry,
permissions, obligations, payment.
"""
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def edge(label: str, default: Any = None, *, reference: bool = False,
         closed_catalog: bool = False, **kwargs: Any) -> Any:
    jse = dict(kwargs.pop("json_schema_extra", {}) or {})
    jse["edge_label"] = label
    if reference:
        jse["graph_reference"] = True
    if closed_catalog:
        jse["reference_closed_catalog"] = True
    if "default_factory" in kwargs:
        df = kwargs.pop("default_factory")
        return Field(default_factory=df, json_schema_extra=jse, **kwargs)
    return Field(default, json_schema_extra=jse, **kwargs)


class Party(BaseModel):
    model_config = ConfigDict(json_schema_extra={"is_entity": True,
                                                 "graph_id_fields": ["name"]})
    name: str = Field(..., description="Legal name of the contracting party")
    role: Optional[str] = Field(None, description="Role, e.g. Supplier, Customer, Manufacturer")


class Term(BaseModel):
    model_config = ConfigDict(json_schema_extra={"is_entity": False})
    effective_date: Optional[str] = Field(None, description="Effective/commencement date, verbatim")
    expiry_date: Optional[str] = Field(None, description="Expiry or end date, verbatim")
    duration: Optional[str] = Field(None, description="Relative duration, e.g. 'nine (9) months'")
    renewal: Optional[str] = Field(None, description="Renewal or evergreen terms, verbatim")


class Permission(BaseModel):
    model_config = ConfigDict(json_schema_extra={"is_entity": True,
                                                 "graph_id_fields": ["text"]})
    text: str = Field(..., description="The permission or restriction clause, verbatim")
    polarity: Optional[str] = Field(None, description="'grants' or 'restricts'")
    condition: Optional[str] = Field(None, description="Any precondition, e.g. prior written consent")


class Obligation(BaseModel):
    model_config = ConfigDict(json_schema_extra={"is_entity": True,
                                                 "graph_id_fields": ["text"]})
    text: str = Field(..., description="The obligation clause, verbatim")
    obligor: Optional[str] = Field(None, description="Party bearing the obligation")


class PaymentTerm(BaseModel):
    model_config = ConfigDict(json_schema_extra={"is_entity": False})
    amount: Optional[str] = Field(None, description="Monetary amount, verbatim")
    currency: Optional[str] = None
    net_days: Optional[str] = Field(None, description="Payment window, e.g. 'net 30'")


class ContractSection(BaseModel):
    model_config = ConfigDict(json_schema_extra={"is_entity": True,
                                                 "graph_id_fields": ["heading"]})
    heading: str = Field(..., description="Section or clause heading as it appears")
    summary: Optional[str] = Field(None, description="One sentence on what this section does")
    permissions: List[Permission] = edge("GRANTS", default_factory=list)
    obligations: List[Obligation] = edge("OBLIGATES", default_factory=list)


class Contract(BaseModel):
    """Root template."""
    model_config = ConfigDict(json_schema_extra={"is_entity": True,
                                                 "graph_id_fields": ["title"]})
    title: str = Field(..., description="Title of the agreement")
    parties: List[Party] = edge("PARTY_TO", default_factory=list)
    term: Optional[Term] = Field(None, description="Term, expiry and renewal")
    payment: Optional[PaymentTerm] = Field(None, description="Payment terms")
    sections: List[ContractSection] = edge("CONTAINS", default_factory=list)
