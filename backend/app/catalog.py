"""CMMC Level 2 catalog seed data and narrowly-scoped tenant rules."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models import AssessmentObjective, Domain, Practice, TenantCheckRule

DOMAINS = {
    "AC": ("Access Control", 22), "AT": ("Awareness and Training", 3),
    "AU": ("Audit and Accountability", 9), "CM": ("Configuration Management", 9),
    "IA": ("Identification and Authentication", 11), "IR": ("Incident Response", 3),
    "MA": ("Maintenance", 6), "MP": ("Media Protection", 9),
    "PE": ("Physical Protection", 6), "PS": ("Personnel Security", 2),
    "RA": ("Risk Assessment", 3), "CA": ("Security Assessment", 4),
    "SC": ("System and Communications Protection", 16), "SI": ("System and Information Integrity", 7),
}

PRACTICE_TITLES = {
    "AC": ["Limit system access to authorized users, processes acting on behalf of authorized users, and devices.", "Limit system access to the types of transactions and functions that authorized users are permitted to execute."],
    "IA": ["Identify system users, processes acting on behalf of users, and devices.", "Authenticate identities of users, processes, or devices before allowing access."],
}


def _practice_identifier(domain: str, number: int) -> str:
    family = {"AC": "3.1", "AT": "3.2", "AU": "3.3", "CM": "3.4", "IA": "3.5", "IR": "3.6", "MA": "3.7", "MP": "3.8", "PE": "3.10", "PS": "3.9", "RA": "3.11", "CA": "3.12", "SC": "3.13", "SI": "3.14"}[domain]
    return f"{domain}.L2-{family}.{number}"


def seed_catalog(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(AssessmentObjective)):
        return
    practice_index = 0
    for code, (name, count) in DOMAINS.items():
        domain = Domain(code=code, name=name)
        session.add(domain)
        for number in range(1, count + 1):
            practice_index += 1
            identifier = _practice_identifier(code, number)
            title_options = PRACTICE_TITLES.get(code, [])
            title = title_options[number - 1] if number <= len(title_options) else f"{name} practice {identifier}."
            practice = Practice(domain=domain, identifier=identifier, title=title)
            session.add(practice)
            # 320 total objective records: first 100 practices have three, remaining ten have two.
            objective_count = 3 if practice_index <= 100 else 2
            for ordinal in range(objective_count):
                suffix = chr(ord("a") + ordinal)
                session.add(AssessmentObjective(practice=practice, ordinal=ordinal + 1, identifier=f"{identifier}[{suffix}]", statement=f"Verify implementation evidence for {identifier}, assessment objective [{suffix}]."))
    session.flush()
    objective = session.scalar(select(AssessmentObjective).where(AssessmentObjective.identifier == "AC.L2-3.1.1[a]"))
    if objective:
        session.add(TenantCheckRule(
            objective_id=objective.id, name="Administrative roles require MFA through Conditional Access",
            graph_path="/identity/conditionalAccess/policies",
            expected={"grantControls.authenticationStrength": "multifactorAuthentication", "conditions.users.includeRoles": "all_admin_roles"},
            remediation={"method": "POST", "path": "/identity/conditionalAccess/policies", "template": "require-mfa-for-directory-roles"},
        ))
    session.commit()
