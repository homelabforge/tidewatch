"""Analytics schemas for TideWatch dashboards."""


from pydantic import BaseModel


class FrequencyPoint(BaseModel):
    date: str
    count: int


class VulnerabilityPoint(BaseModel):
    date: str
    cves_fixed: int


class DistributionItem(BaseModel):
    label: str
    value: int


class AnalyticsSummary(BaseModel):
    period_days: int
    total_updates: int
    successful_updates: int
    failed_updates: int
    update_frequency: list[FrequencyPoint]
    vulnerability_trends: list[VulnerabilityPoint]
    policy_distribution: list[DistributionItem]
    avg_update_duration_seconds: float
    total_cves_fixed: int
    updates_with_cves: int  # Count of updates that fixed at least one CVE
