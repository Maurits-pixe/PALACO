use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_evolution::EvolutionProposal;
use palaco_foundation::{
    AuthorityState, ContractDisposition, ContractError, EvidenceRef, FailClosed, Validatable,
};
use palaco_kernel::KernelCycle;
use palaco_quay::ProvenanceRecord;
use palaco_runtime::RuntimePlan;

fn cycle(authority: AuthorityState) -> Result<KernelCycle, ContractError> {
    let evidence = EvidenceRef::new("PVS-002-EVIDENCE-001")?;
    let event = EventEnvelope::new("execution.requested", evidence);
    let record = ProvenanceRecord::new(event, authority);
    let boundary = ExecutionBoundary::new(record);
    let plan = RuntimePlan::new(boundary);
    Ok(KernelCycle::new(plan))
}

#[test]
fn authorized_evidence_path_reaches_execute_without_widening_authority() -> Result<(), ContractError>
{
    let cycle = cycle(AuthorityState::Authorized)?;

    assert_eq!(cycle.disposition(), ContractDisposition::Execute);
    assert!(cycle.can_execute());
    cycle.validate()?;

    Ok(())
}

#[test]
fn revoked_authority_remains_denied_across_all_downstream_boundaries() -> Result<(), ContractError>
{
    let cycle = cycle(AuthorityState::Revoked)?;

    assert_eq!(cycle.disposition(), ContractDisposition::Deny);
    assert!(!cycle.can_execute());
    assert_eq!(cycle.fail_closed(), ContractDisposition::Deny);

    Ok(())
}

#[test]
fn indoubt_authority_is_held_and_never_executes() -> Result<(), ContractError> {
    let cycle = cycle(AuthorityState::InDoubt)?;

    assert_eq!(cycle.disposition(), ContractDisposition::Hold);
    assert!(!cycle.can_execute());

    Ok(())
}

#[test]
fn empty_evidence_reference_is_rejected_before_event_transport() {
    assert_eq!(EvidenceRef::new(""), Err(ContractError::MissingEvidence));
}

#[test]
fn evolution_proposal_cannot_self_authorize_execution() -> Result<(), ContractError> {
    let evidence = EvidenceRef::new("PVS-002-EVOLUTION-001")?;
    let proposal = EvolutionProposal::new(evidence);

    proposal.validate()?;
    assert_eq!(proposal.requested_disposition(), ContractDisposition::Hold);

    Ok(())
}
